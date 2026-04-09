"""
Unit tests for the check engine — no cluster or AI required.
Run: python -m pytest tests/ -v
"""

import pytest
from checks.engine import CheckEngine, _get_nested
from models import CheckRule, ResourceContext, Severity, Status


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_resource(raw: dict, kind: str = "Deployment", name: str = "test-app") -> ResourceContext:
    return ResourceContext(kind=kind, name=name, namespace="default", source="manifest", raw=raw)


def make_rule(id: str, selectors: dict, severity: str = "high") -> CheckRule:
    return CheckRule(
        id=id, name=f"Rule {id}", description="test",
        severity=Severity(severity), category="test",
        remediation="fix it", selectors=selectors,
    )


# ── _get_nested tests ─────────────────────────────────────────────────────────

def test_get_nested_simple():
    obj = {"spec": {"replicas": 3}}
    assert _get_nested(obj, "spec.replicas") == [3]


def test_get_nested_wildcard():
    obj = {"spec": {"template": {"spec": {"containers": [
        {"name": "a", "image": "img:latest"},
        {"name": "b", "image": "img:v1.0"},
    ]}}}}
    images = _get_nested(obj, "spec.template.spec.containers[*].image")
    assert images == ["img:latest", "img:v1.0"]


def test_get_nested_missing():
    assert _get_nested({}, "spec.replicas") == []


def test_get_nested_nested_missing():
    obj = {"spec": {}}
    assert _get_nested(obj, "spec.template.spec.containers[*].image") == []


# ── required_present ──────────────────────────────────────────────────────────

def test_required_present_pass():
    resource = make_resource({"spec": {"replicas": 3}})
    rule     = make_rule("r1", {"path": "spec.replicas", "required_present": True})
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.PASS


def test_required_present_fail():
    resource = make_resource({"spec": {}})
    rule     = make_rule("r1", {"path": "spec.replicas", "required_present": True})
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.FAIL


# ── required_value ────────────────────────────────────────────────────────────

def test_required_value_pass():
    resource = make_resource({"spec": {"strategy": {"type": "RollingUpdate"}}})
    rule     = make_rule("r2", {"path": "spec.strategy.type", "required_value": "RollingUpdate"})
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.PASS


def test_required_value_fail():
    resource = make_resource({"spec": {"strategy": {"type": "Recreate"}}})
    rule     = make_rule("r2", {"path": "spec.strategy.type", "required_value": "RollingUpdate"})
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.FAIL


# ── bad_value ─────────────────────────────────────────────────────────────────

def test_bad_value_fail():
    resource = make_resource({"spec": {"template": {"spec": {"containers": [
        {"securityContext": {"privileged": True}}
    ]}}}})
    rule = make_rule("r3", {
        "path": "spec.template.spec.containers[*].securityContext.privileged",
        "bad_value": True,
    })
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.FAIL


def test_bad_value_pass():
    resource = make_resource({"spec": {"template": {"spec": {"containers": [
        {"securityContext": {"privileged": False}}
    ]}}}})
    rule = make_rule("r3", {
        "path": "spec.template.spec.containers[*].securityContext.privileged",
        "bad_value": True,
    })
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.PASS


# ── bad_suffix ────────────────────────────────────────────────────────────────

def test_bad_suffix_latest_fail():
    resource = make_resource({"spec": {"template": {"spec": {"containers": [
        {"image": "myapp:latest"}
    ]}}}})
    rule = make_rule("r4", {
        "path": "spec.template.spec.containers[*].image",
        "bad_suffix": ":latest",
    })
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.FAIL


def test_bad_suffix_pinned_pass():
    resource = make_resource({"spec": {"template": {"spec": {"containers": [
        {"image": "myapp:v1.2.3"}
    ]}}}})
    rule = make_rule("r4", {
        "path": "spec.template.spec.containers[*].image",
        "bad_suffix": ":latest",
    })
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.PASS


# ── min_value ─────────────────────────────────────────────────────────────────

def test_min_value_fail():
    resource = make_resource({"spec": {"replicas": 1}})
    rule     = make_rule("r5", {"path": "spec.replicas", "min_value": 2})
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.FAIL


def test_min_value_pass():
    resource = make_resource({"spec": {"replicas": 3}})
    rule     = make_rule("r5", {"path": "spec.replicas", "min_value": 2})
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.PASS


# ── required_contains ─────────────────────────────────────────────────────────

def test_required_contains_pass():
    resource = make_resource({"spec": {"template": {"spec": {"containers": [
        {"securityContext": {"capabilities": {"drop": ["ALL", "NET_ADMIN"]}}}
    ]}}}})
    rule = make_rule("r6", {
        "path": "spec.template.spec.containers[*].securityContext.capabilities.drop",
        "required_contains": "ALL",
    })
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.PASS


def test_required_contains_fail():
    resource = make_resource({"spec": {"template": {"spec": {"containers": [
        {"securityContext": {"capabilities": {"drop": ["NET_ADMIN"]}}}
    ]}}}})
    rule = make_rule("r6", {
        "path": "spec.template.spec.containers[*].securityContext.capabilities.drop",
        "required_contains": "ALL",
    })
    findings = CheckEngine([rule]).evaluate([resource])
    assert findings[0].status == Status.FAIL


# ── Scoring ───────────────────────────────────────────────────────────────────

def test_score_all_pass():
    from models import AuditResults, Finding
    results = AuditResults(namespace="default", source="manifest", profile_name="test")
    results.findings = [
        Finding("r1", "R1", "critical", "pass", "test", make_resource({})),
        Finding("r2", "R2", "high",     "pass", "test", make_resource({})),
    ]
    results.compute_score()
    assert results.score == 100.0
    assert results.grade == "A"


def test_score_all_fail():
    from models import AuditResults, Finding
    results = AuditResults(namespace="default", source="manifest", profile_name="test")
    results.findings = [
        Finding("r1", "R1", "critical", "fail", "test", make_resource({})),
        Finding("r2", "R2", "high",     "fail", "test", make_resource({})),
    ]
    results.compute_score()
    assert results.score == 0.0
    assert results.grade == "F"
