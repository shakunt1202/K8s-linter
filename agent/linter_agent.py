"""
AI Linter Agent — orchestrates sources, check engine, and a pluggable AI provider.
Emits verbose per-rule and per-resource log lines for real-time UI streaming.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List

from checks.engine import CheckEngine
from models import AuditResults, Finding
from profiles.loader import ProfileLoader
from sources.cluster_source import ClusterSource
from sources.manifest_source import ManifestSource

import agent.providers.anthropic_provider
import agent.providers.ollama_provider
import agent.providers.openai_provider
import agent.providers.mock_provider

from agent.providers import BaseProvider, get_provider, list_providers

logger = logging.getLogger(__name__)

REMEDIATION_SYSTEM_PROMPT = """You are a senior DevOps / Kubernetes security engineer with deep expertise in
cluster hardening, CIS benchmarks, and secure deployment practices.

You are given a single Kubernetes lint finding - a security or reliability check that FAILED.
Your job is to produce a concise, actionable remediation plan that a developer can follow immediately.

Guidelines:
- Be specific: include exact field names, example YAML snippets, and kubectl commands where relevant
- Keep the response under 200 words
- Structure: 1 sentence of WHY this matters, then 2-4 numbered steps to fix it
- Tailor the advice to the actual resource name and kind provided
- Do not repeat the problem statement - just the fix
"""

SUMMARY_SYSTEM_PROMPT = """You are a senior DevOps engineer writing an executive audit summary for a Kubernetes
environment lint report.

You will receive a JSON object containing the audit results: score, grade, findings breakdown,
and namespace/profile details.

Write a concise executive summary (4-6 sentences) that:
1. States the overall health of the cluster/manifests
2. Calls out the most critical findings by category
3. Gives a prioritised action recommendation
4. Is written for a technical lead - direct and specific, no marketing language

Keep it under 150 words.
"""


class LinterAgent:
    def __init__(
        self,
        source:            str,
        namespace:         str,
        manifest_path:     str,
        profile_path:      str,
        provider:          str  = "anthropic",
        model:             str  = "",
        provider_base_url: str  = "",
        provider_api_key:  str  = "",
        ollama_url:        str  = "http://localhost:11434",
        ai_remediation:    bool = True,
        **kwargs,
    ):
        self.source         = source
        self.namespace      = namespace
        self.manifest_path  = manifest_path
        self.profile_path   = profile_path
        self.ai_remediation = ai_remediation
        self.provider_name  = provider
        self.model          = model or self._default_model(provider)

        provider_kwargs: dict = {}
        if provider == "ollama":
            provider_kwargs["base_url"] = provider_base_url or ollama_url
        elif provider in ("openai", "openai-compat"):
            if provider_base_url:
                provider_kwargs["base_url"] = provider_base_url
            if provider_api_key:
                provider_kwargs["api_key"] = provider_api_key
        elif provider == "anthropic":
            if provider_api_key:
                provider_kwargs["api_key"] = provider_api_key

        if ai_remediation:
            try:
                self._provider: BaseProvider = get_provider(provider, self.model, **provider_kwargs)
            except Exception as e:
                logger.warning("Provider init failed (%s), falling back to mock: %s", provider, e)
                from agent.providers.mock_provider import MockProvider
                self._provider = MockProvider()
        else:
            from agent.providers.mock_provider import MockProvider
            self._provider = MockProvider()

    @staticmethod
    def _default_model(provider: str) -> str:
        return {
            "anthropic":     "claude-sonnet-4-20250514",
            "ollama":        "llama3",
            "openai":        "gpt-4o",
            "openai-compat": "llama3-70b-8192",
            "mock":          "mock-model",
        }.get(provider, "")

    async def run(self) -> AuditResults:
        # ── Stage 1: Profile ──────────────────────────────────────────────────
        print("[1/5] Loading compliance profile...")
        profile = ProfileLoader(self.profile_path).load()
        rules   = profile.enabled_rules()
        print(f"PROFILE  {profile.name} v{profile.version}")
        print(f"RULES    {len(rules)} checks enabled")
        for rule in rules:
            sev = rule.severity.value if hasattr(rule.severity, 'value') else str(rule.severity)
            print(f"CHECK    [{sev.upper():8s}] {rule.id} - {rule.name}")

        # ── Stage 2: Resources ────────────────────────────────────────────────
        print("[2/5] Fetching Kubernetes resources...")
        resources = self._fetch_resources()
        print(f"FETCHED  {len(resources)} resource(s) from ns={self.namespace} src={self.source}")
        for r in resources:
            print(f"RESOURCE {r.kind}/{r.name} ns={r.namespace} src={r.source}")

        # ── Stage 3: Check engine ─────────────────────────────────────────────
        print("[3/5] Running check engine...")
        engine   = CheckEngine(rules)
        findings = engine.evaluate_verbose(resources, log_fn=print)
        n_pass = sum(1 for f in findings if f.status == "pass")
        n_fail = sum(1 for f in findings if f.status == "fail")
        print(f"ENGINE   {len(findings)} findings - pass={n_pass} fail={n_fail}")

        results = AuditResults(
            namespace=self.namespace, source=self.source,
            profile_name=profile.name, findings=findings,
            resources_scanned=len(resources), checks_run=len(findings),
        )
        results.compute_score()

        # ── Stage 4/5: AI ──────────────────────────────────────────────────────
        if self.ai_remediation:
            print(f"[4/5] AI agent [{self.provider_name} / {self.model}] generating remediations...")
            await self._enrich_with_ai(results)
            print(f"[5/5] AI agent [{self.provider_name}] writing executive summary...")
            results.ai_summary = await self._generate_summary(results)
        else:
            print("[4/5] AI remediation disabled.")
            print("[5/5] Skipped.")

        results.compute_score()
        print(f"COMPLETE score={results.score}% grade={results.grade}")
        return results

    def _fetch_resources(self):
        resources = []
        if self.source in ("cluster", "both"):
            resources.extend(ClusterSource(self.namespace).fetch())
        if self.source in ("manifest", "both"):
            resources.extend(ManifestSource(self.manifest_path).fetch())
        return resources

    async def _enrich_with_ai(self, results: AuditResults) -> None:
        failures = [f for f in results.findings if f.status == "fail"]
        if not failures:
            print("AI       No failures to remediate.")
            return
        concurrency = 3 if self.provider_name == "ollama" else 5
        sem = asyncio.Semaphore(concurrency)
        await asyncio.gather(*[self._remediate_finding(f, sem) for f in failures])
        print(f"AI       Remediation done for {len(failures)} failing checks.")

    async def _remediate_finding(self, finding: Finding, sem: asyncio.Semaphore) -> None:
        async with sem:
            print(f"AI-REM   {finding.rule_id} on {finding.resource.kind}/{finding.resource.name}")
            try:
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda: self._provider.complete(
                        system=REMEDIATION_SYSTEM_PROMPT,
                        user=self._finding_to_prompt(finding),
                        max_tokens=400,
                    )
                )
                finding.remediation_ai = resp.text
                finding.evidence["ai_provider"] = resp.provider
                finding.evidence["ai_model"]    = resp.model
            except Exception as e:
                logger.warning("AI remediation failed for %s (%s): %s",
                               finding.rule_id, self.provider_name, e)
                finding.remediation_ai = (
                    f"[AI unavailable - {type(e).__name__}: {e}]\n"
                    f"Static hint: {finding.remediation_static}"
                )

    def _finding_to_prompt(self, f: Finding) -> str:
        return (
            f"Rule ID    : {f.rule_id}\n"
            f"Rule name  : {f.rule_name}\n"
            f"Severity   : {f.severity}\n"
            f"Category   : {f.category}\n"
            f"Resource   : {f.resource.kind}/{f.resource.name} in namespace '{f.resource.namespace}'\n"
            f"Source     : {f.resource.source}\n"
            f"Detail     : {f.detail}\n"
            f"Evidence   : {json.dumps(f.evidence, indent=2)}\n\n"
            f"Static remediation hint: {f.remediation_static}\n\n"
            f"Please provide an actionable AI-enhanced remediation plan for this specific finding."
        )

    async def _generate_summary(self, results: AuditResults) -> str:
        data = {
            "namespace": results.namespace, "profile": results.profile_name,
            "source": results.source, "score": results.score, "grade": results.grade,
            "resources_scanned": results.resources_scanned, "checks_run": results.checks_run,
            "summary": results.summary,
            "failing_by_category": {
                cat: sum(1 for f in results.findings if f.status == "fail" and f.category == cat)
                for cat in set(f.category for f in results.findings if f.status == "fail")
            },
            "critical_failures": [
                {"rule": f.rule_name, "resource": f"{f.resource.kind}/{f.resource.name}", "detail": f.detail}
                for f in results.findings if f.status == "fail" and f.severity == "critical"
            ],
        }
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: self._provider.complete(
                    system=SUMMARY_SYSTEM_PROMPT,
                    user=f"Audit results:\n{json.dumps(data, indent=2)}",
                    max_tokens=300,
                )
            )
            return resp.text
        except Exception as e:
            logger.warning("AI summary failed (%s): %s", self.provider_name, e)
            return f"AI summary unavailable ({type(e).__name__}: {e})."
