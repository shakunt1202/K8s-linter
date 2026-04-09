"""
Reporter — renders AuditResults in terminal, JSON, and Markdown formats.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List

from models import AuditResults, Finding


SEVERITY_COLORS = {
    "critical": "\033[91m",   # bright red
    "high":     "\033[93m",   # yellow
    "medium":   "\033[94m",   # blue
    "low":      "\033[90m",   # dark grey
}
STATUS_ICONS = {
    "pass": "\033[92m✔\033[0m",   # green
    "fail": "\033[91m✖\033[0m",   # red
    "warn": "\033[93m!\033[0m",   # yellow
    "skip": "\033[90m–\033[0m",   # grey
}
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
TEAL   = "\033[96m"
WHITE  = "\033[97m"


class Reporter:
    def __init__(self, results: AuditResults):
        self.results   = results
        self.timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    # ── Terminal ─────────────────────────────────────────────────────────────

    def print_terminal(self) -> None:
        r = self.results
        print(f"\n{BOLD}{TEAL}{'═'*60}{RESET}")
        print(f"{BOLD}  K8s Lint Report{RESET}  ·  {DIM}{self.timestamp}{RESET}")
        print(f"  Namespace : {WHITE}{r.namespace}{RESET}")
        print(f"  Profile   : {WHITE}{r.profile_name}{RESET}")
        print(f"  Source    : {WHITE}{r.source}{RESET}")
        print(f"{TEAL}{'─'*60}{RESET}")

        # Score block
        grade_color = {
            "A": "\033[92m", "B": "\033[92m", "C": "\033[93m",
            "D": "\033[91m", "F": "\033[91m",
        }.get(r.grade, RESET)
        print(f"\n  Score  : {BOLD}{grade_color}{r.score}%  [{r.grade}]{RESET}")
        print(f"  Passed : {BOLD}\033[92m{r.summary.get('pass', 0)}{RESET}  "
              f"Failed : {BOLD}\033[91m{r.summary.get('fail', 0)}{RESET}  "
              f"Warned : {BOLD}\033[93m{r.summary.get('warn', 0)}{RESET}  "
              f"Skipped: {DIM}{r.summary.get('skip', 0)}{RESET}")

        # AI executive summary
        if r.ai_summary:
            print(f"\n{TEAL}{'─'*60}{RESET}")
            print(f"{BOLD}  AI Executive Summary{RESET}")
            for line in r.ai_summary.splitlines():
                print(f"  {line}")

        # Findings by category
        categories = sorted(set(f.category for f in r.findings))
        for cat in categories:
            cat_findings = [f for f in r.findings if f.category == cat]
            fails = sum(1 for f in cat_findings if f.status == "fail")
            print(f"\n{TEAL}{'─'*60}{RESET}")
            print(f"{BOLD}  {cat.upper()}{RESET}  {DIM}({fails} failure(s) / {len(cat_findings)} checks){RESET}")

            for finding in sorted(cat_findings, key=lambda x: (x.status != "fail", x.severity)):
                icon  = STATUS_ICONS.get(finding.status, "?")
                sev   = finding.severity
                sc    = SEVERITY_COLORS.get(sev, "")
                print(f"\n    {icon}  {BOLD}{finding.rule_name}{RESET}  "
                      f"[{sc}{sev.upper()}{RESET}]  "
                      f"{DIM}{finding.resource.kind}/{finding.resource.name}{RESET}")
                if finding.detail:
                    print(f"       {DIM}↳ {finding.detail}{RESET}")
                if finding.status == "fail":
                    if finding.remediation_ai:
                        print(f"\n       {TEAL}AI Remediation:{RESET}")
                        for line in finding.remediation_ai.splitlines()[:8]:
                            print(f"       {line}")
                    elif finding.remediation_static:
                        print(f"\n       {DIM}Hint: {finding.remediation_static[:120]}...{RESET}")

        print(f"\n{TEAL}{'═'*60}{RESET}\n")

    # ── JSON ─────────────────────────────────────────────────────────────────

    def to_json(self) -> str:
        r = self.results
        data = {
            "generated_at":      self.timestamp,
            "namespace":         r.namespace,
            "profile":           r.profile_name,
            "source":            r.source,
            "score":             r.score,
            "grade":             r.grade,
            "resources_scanned": r.resources_scanned,
            "checks_run":        r.checks_run,
            "summary":           r.summary,
            "ai_summary":        r.ai_summary,
            "findings": [self._finding_to_dict(f) for f in r.findings],
        }
        return json.dumps(data, indent=2)

    def _finding_to_dict(self, f: Finding) -> dict:
        return {
            "rule_id":          f.rule_id,
            "rule_name":        f.rule_name,
            "severity":         f.severity,
            "status":           f.status,
            "category":         f.category,
            "resource_kind":    f.resource.kind,
            "resource_name":    f.resource.name,
            "namespace":        f.resource.namespace,
            "source":           f.resource.source,
            "detail":           f.detail,
            "remediation_static": f.remediation_static,
            "remediation_ai":   f.remediation_ai,
            "evidence":         f.evidence,
        }

    # ── Markdown ─────────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        r = self.results
        lines = [
            f"# K8s Environment Lint Report",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Generated | `{self.timestamp}` |",
            f"| Namespace | `{r.namespace}` |",
            f"| Profile | {r.profile_name} |",
            f"| Source | {r.source} |",
            f"| **Score** | **{r.score}% [{r.grade}]** |",
            f"| Passed | {r.summary.get('pass', 0)} |",
            f"| Failed | {r.summary.get('fail', 0)} |",
            f"| Warnings | {r.summary.get('warn', 0)} |",
            f"",
        ]

        if r.ai_summary:
            lines += ["## Executive Summary", "", r.ai_summary, ""]

        categories = sorted(set(f.category for f in r.findings))
        for cat in categories:
            cat_findings = [f for f in r.findings if f.category == cat]
            fails = sum(1 for f in cat_findings if f.status == "fail")
            lines.append(f"## {cat.capitalize()}  _(failures: {fails})_")
            lines.append("")
            lines.append("| Status | Rule | Severity | Resource | Detail |")
            lines.append("|--------|------|----------|----------|--------|")
            for f in sorted(cat_findings, key=lambda x: (x.status != "fail", x.severity)):
                icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(f.status, "?")
                lines.append(
                    f"| {icon} | {f.rule_name} | `{f.severity}` | "
                    f"`{f.resource.kind}/{f.resource.name}` | {f.detail[:80]} |"
                )
            lines.append("")

            # Remediation blocks for failures
            failures = [f for f in cat_findings if f.status == "fail"]
            if failures:
                lines.append("### Remediations")
                lines.append("")
                for f in failures:
                    lines.append(f"#### `{f.rule_id}` — {f.rule_name}")
                    lines.append(f"**Resource:** `{f.resource.kind}/{f.resource.name}`  ")
                    lines.append(f"**Severity:** `{f.severity}`  ")
                    lines.append("")
                    if f.remediation_ai:
                        lines.append(f.remediation_ai)
                    else:
                        lines.append(f"> {f.remediation_static}")
                    lines.append("")

        return "\n".join(lines)
