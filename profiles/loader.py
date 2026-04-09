"""
Profile loader — reads a custom YAML compliance profile and returns CheckRule objects.

Profile schema:
  name: "My Org K8s Hardening"
  version: "1.0"
  description: "..."
  rules:
    - id: sec-01
      name: No privileged containers
      description: ...
      severity: critical
      category: security
      enabled: true
      remediation: "Set securityContext.privileged: false"
      selectors:
        path: "spec.template.spec.containers[*].securityContext.privileged"
        bad_value: true
      env_overrides:
        development:
          severity: low
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import List

from models import CheckRule, Severity


class ProfileLoader:
    def __init__(self, profile_path: str):
        self.profile_path = Path(profile_path)
        self._raw: dict = {}
        self.name: str = "custom"
        self.version: str = "1.0"
        self.description: str = ""
        self.rules: List[CheckRule] = []

    def load(self) -> "ProfileLoader":
        if not self.profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {self.profile_path}")

        with open(self.profile_path) as f:
            self._raw = yaml.safe_load(f)

        self.name        = self._raw.get("name", "custom")
        self.version     = self._raw.get("version", "1.0")
        self.description = self._raw.get("description", "")
        self.rules       = [self._parse_rule(r) for r in self._raw.get("rules", [])]
        return self

    def _parse_rule(self, raw: dict) -> CheckRule:
        return CheckRule(
            id=raw["id"],
            name=raw["name"],
            description=raw.get("description", ""),
            severity=Severity(raw.get("severity", "medium")),
            category=raw.get("category", "general"),
            remediation=raw.get("remediation", ""),
            enabled=raw.get("enabled", True),
            env_overrides=raw.get("env_overrides", {}),
            selectors=raw.get("selectors", {}),
        )

    def enabled_rules(self, environment: str = "production") -> List[CheckRule]:
        """Return rules that are enabled, applying env-level overrides."""
        result = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            # Apply env override (e.g. downgrade severity in dev)
            if environment in rule.env_overrides:
                override = rule.env_overrides[environment]
                if "severity" in override:
                    rule = CheckRule(
                        **{**rule.__dict__, "severity": Severity(override["severity"])}
                    )
                if override.get("skip"):
                    continue
            result.append(rule)
        return result
