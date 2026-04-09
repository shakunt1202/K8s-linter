"""
Check engine — evaluates CheckRules against ResourceContext objects.
Uses a combination of JSONPath-style field traversal and kind-specific logic.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from models import CheckRule, Finding, ResourceContext, Status

logger = logging.getLogger(__name__)


def _get_nested(obj: Any, path: str) -> Any:
    """Traverse a dot/bracket-notation path through a nested dict/list.
    Supports simple paths like 'spec.replicas' and
    wildcard paths like 'spec.template.spec.containers[*].image'.
    Returns a list of matched values (always a list for uniformity).
    """
    if not path or obj is None:
        return []

    parts = _split_path(path)
    return _traverse(obj, parts)


def _split_path(path: str) -> List[str]:
    parts = []
    for segment in path.replace("[*]", ".*").split("."):
        parts.append(segment)
    return parts


def _traverse(obj: Any, parts: List[str]) -> List[Any]:
    if not parts:
        return [obj]
    head, *tail = parts
    if head == "*":
        if isinstance(obj, list):
            results = []
            for item in obj:
                results.extend(_traverse(item, tail))
            return results
        return []
    if isinstance(obj, dict):
        val = obj.get(head)
        if val is None:
            return []
        return _traverse(val, tail)
    return []


class CheckEngine:
    def __init__(self, rules: List[CheckRule]):
        self.rules = rules

    def evaluate(self, resources: List[ResourceContext]) -> List[Finding]:
        findings = []
        for resource in resources:
            for rule in self.rules:
                finding = self._apply_rule(rule, resource)
                if finding:
                    findings.append(finding)
        return findings

    def evaluate_verbose(self, resources, log_fn=None):
        findings = []
        for resource in resources:
            for rule in self.rules:
                finding = self._apply_rule(rule, resource)
                if finding:
                    findings.append(finding)
                    if log_fn:
                        icon = "PASS" if finding.status == "pass" else "FAIL" if finding.status == "fail" else "WARN"
                        sev = finding.severity.value if hasattr(finding.severity, 'value') else str(finding.severity)
                        log_fn(f"{icon}     [{sev.upper():8s}] {rule.id} {resource.kind}/{resource.name} - {finding.detail[:80]}")
        return findings

    def _apply_rule(self, rule: CheckRule, resource: ResourceContext) -> Optional[Finding]:
        """Dispatch to the right check method based on selector shape."""
        sel = rule.selectors

        # ── kinds guard ──────────────────────────────────────────────────────
        # If the rule defines a `kinds` list, only evaluate it against matching
        # resource kinds. Any other kind is silently skipped — no finding is
        # produced at all, which keeps reports clean and avoids false positives
        # like checking NodePort on a Deployment.
        allowed_kinds = sel.get("kinds")
        if allowed_kinds and resource.kind not in allowed_kinds:
            return None

        # Kind-level check (e.g. NetworkPolicy must exist in namespace)
        if sel.get("kind"):
            return self._check_kind_presence(rule, resource, sel)

        # Field path checks
        if "path" in sel:
            return self._check_field(rule, resource, sel)

        # Multi-path checks (e.g. hostPID + hostIPC + hostNetwork)
        if "paths" in sel:
            return self._check_multi_field(rule, resource, sel)

        return None

    # ── Field checks ────────────────────────────────────────────────────────

    def _check_field(self, rule: CheckRule, resource: ResourceContext, sel: Dict) -> Optional[Finding]:
        path = sel["path"]
        values = _get_nested(resource.raw, path)

        def _make(status: str, detail: str) -> Finding:
            return Finding(
                rule_id=rule.id, rule_name=rule.name, severity=rule.severity,
                status=status, category=rule.category,
                resource=resource, detail=detail,
                remediation_static=rule.remediation,
                evidence={"path": path, "found": values},
            )

        # required_present: field must exist and not be None/empty
        if sel.get("required_present"):
            if not values or all(v is None for v in values):
                return _make(Status.FAIL, f"Required field '{path}' is missing or null.")
            return _make(Status.PASS, f"Field '{path}' is present.")

        # required_value: field must equal this exact value
        if "required_value" in sel:
            rv = sel["required_value"]
            if not values:
                return _make(Status.FAIL, f"Field '{path}' is absent (expected {rv!r}).")
            mismatches = [v for v in values if v != rv]
            if mismatches:
                return _make(Status.FAIL, f"Field '{path}' = {mismatches!r}, expected {rv!r}.")
            return _make(Status.PASS, f"Field '{path}' correctly set to {rv!r}.")

        # bad_value: field must NOT equal this value
        if "bad_value" in sel:
            bv = sel["bad_value"]
            matches = [v for v in values if v == bv]
            if matches:
                return _make(Status.FAIL, f"Field '{path}' is set to disallowed value {bv!r}.")
            if not values:
                return _make(Status.PASS, f"Field '{path}' absent (bad value {bv!r} not present).")
            return _make(Status.PASS, f"Field '{path}' = {values!r} — OK.")

        # bad_suffix: field value must not end with this string (e.g. :latest)
        if "bad_suffix" in sel:
            bs = sel["bad_suffix"]
            bad = [v for v in values if isinstance(v, str) and v.endswith(bs)]
            if bad:
                return _make(Status.FAIL, f"Image tag ends with disallowed suffix '{bs}': {bad!r}.")
            return _make(Status.PASS, f"No image tags with suffix '{bs}'.")

        # min_value: numeric field must be >= this
        if "min_value" in sel:
            mv = sel["min_value"]
            if not values:
                return _make(Status.FAIL, f"Field '{path}' is absent (required ≥ {mv}).")
            bad = [v for v in values if (isinstance(v, (int, float)) and v < mv)]
            if bad:
                return _make(Status.FAIL, f"Field '{path}' = {bad!r}, required ≥ {mv}.")
            return _make(Status.PASS, f"Field '{path}' = {values!r} meets minimum of {mv}.")

        # required_contains: list field must contain this value
        if "required_contains" in sel:
            rc = sel["required_contains"]
            for v in values:
                lst = v if isinstance(v, list) else [v]
                if rc in lst:
                    return _make(Status.PASS, f"Field '{path}' contains required value {rc!r}.")
            return _make(Status.FAIL, f"Field '{path}' does not contain required value {rc!r}.")

        return None

    def _check_multi_field(self, rule: CheckRule, resource: ResourceContext, sel: Dict) -> Optional[Finding]:
        paths = sel.get("paths", [])
        bv    = sel.get("bad_value")
        violations = []
        for path in paths:
            values = _get_nested(resource.raw, path)
            if bv is not None and bv in values:
                violations.append(path)
        if violations:
            return Finding(
                rule_id=rule.id, rule_name=rule.name, severity=rule.severity,
                status=Status.FAIL, category=rule.category, resource=resource,
                detail=f"Disallowed value {bv!r} found in: {violations}",
                remediation_static=rule.remediation,
                evidence={"violations": violations},
            )
        return Finding(
            rule_id=rule.id, rule_name=rule.name, severity=rule.severity,
            status=Status.PASS, category=rule.category, resource=resource,
            detail=f"No disallowed values in host namespace fields.",
            remediation_static=rule.remediation,
        )

    def _check_kind_presence(self, rule: CheckRule, resource: ResourceContext, sel: Dict) -> Optional[Finding]:
        """Check that a particular Kind is present in the resource list (namespace-level)."""
        required_kind = sel["kind"]
        # This check only runs against the correct kind
        if resource.kind != required_kind:
            return None
        if sel.get("required_present"):
            return Finding(
                rule_id=rule.id, rule_name=rule.name, severity=rule.severity,
                status=Status.PASS, category=rule.category, resource=resource,
                detail=f"{required_kind} '{resource.name}' is present.",
                remediation_static=rule.remediation,
            )
        return None
