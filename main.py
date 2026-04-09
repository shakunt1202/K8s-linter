#!/usr/bin/env python3
"""
K8s AI Agentic Linter — main entry point.

Usage examples:
  # Anthropic Claude (default)
  python main.py --source both --provider anthropic --model claude-sonnet-4-20250514

  # Local Ollama
  python main.py --source both --provider ollama --model llama3 --ollama-url http://localhost:11434

  # OpenAI
  python main.py --source both --provider openai --model gpt-4o

  # Groq (OpenAI-compatible)
  python main.py --source both --provider openai-compat \
    --model llama3-70b-8192 \
    --provider-base-url https://api.groq.com/openai/v1 \
    --provider-api-key $GROQ_API_KEY

  # LM Studio (local OpenAI-compat)
  python main.py --source both --provider openai-compat \
    --model local-model --provider-base-url http://localhost:1234/v1

  # Dry run (no AI)
  python main.py --source manifest --no-ai-remediation --severity-gate critical
"""

import argparse
import asyncio
import sys
from pathlib import Path

from agent.linter_agent import LinterAgent
from agent.providers import list_providers
from output.reporter import Reporter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="K8s AI Agentic Linter — security & compliance auditor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Source ──────────────────────────────────────────────────────────────
    src = parser.add_argument_group("Source")
    src.add_argument("--source", choices=["cluster", "manifest", "both"],
                     default="both",
                     help="Lint source: live cluster, local manifests, or both")
    src.add_argument("--namespace", "-n", default="default",
                     help="Kubernetes namespace to audit")
    src.add_argument("--path", "-p", default="./manifests",
                     help="Path to YAML/Helm manifest directory")
    src.add_argument("--profile", default="profiles/custom.yaml",
                     help="Path to custom compliance profile YAML")

    # ── AI Provider ─────────────────────────────────────────────────────────
    ai = parser.add_argument_group("AI Provider")
    ai.add_argument("--provider",
                    choices=["anthropic", "ollama", "openai", "openai-compat", "mock"],
                    default="anthropic",
                    help="AI provider to use for remediation and summary")
    ai.add_argument("--model", default="",
                    help="Model name (provider-specific default used if omitted)")
    ai.add_argument("--ollama-url", default="http://localhost:11434",
                    help="Ollama base URL (default: http://localhost:11434)")
    ai.add_argument("--provider-base-url", default="",
                    help="Base URL for openai-compat providers (Groq, Together, LM Studio, etc.)")
    ai.add_argument("--provider-api-key", default="",
                    help="API key for the chosen provider (falls back to env vars)")
    ai.add_argument("--list-providers", action="store_true",
                    help="Print available AI providers and exit")
    ai.add_argument("--ai-remediation", action="store_true", default=True,
                    help="Enable AI-generated remediation (default: on)")
    ai.add_argument("--no-ai-remediation", dest="ai_remediation", action="store_false",
                    help="Disable AI remediation (fast / offline mode)")

    # ── Output ──────────────────────────────────────────────────────────────
    out = parser.add_argument_group("Output")
    out.add_argument("--output", choices=["terminal", "json", "markdown", "all"],
                     default="terminal", help="Output format")
    out.add_argument("--out-file", default=None,
                     help="Write report to file (optional)")
    out.add_argument("--severity-gate", choices=["critical", "high", "medium", "low"],
                     default="high",
                     help="Minimum severity that triggers a non-zero exit code")

    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    if args.list_providers:
        print("\nAvailable AI providers:")
        for p in list_providers():
            print(f"  • {p}")
        print()
        return 0

    print("\n╔══════════════════════════════════════════════════╗")
    print("║       K8s AI Agentic Linter  v2.0.0              ║")
    print("║       Multi-Provider · Custom Profile Engine     ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # Resolve display model name
    from agent.linter_agent import LinterAgent as LA
    display_model = args.model or LA._default_model(args.provider)

    print(f"  ▸ Source        : {args.source}")
    print(f"  ▸ Namespace     : {args.namespace}")
    print(f"  ▸ Profile       : {args.profile}")
    print(f"  ▸ AI provider   : {args.provider} / {display_model}")
    print(f"  ▸ AI remediation: {'enabled' if args.ai_remediation else 'disabled'}")
    print(f"  ▸ Severity gate : {args.severity_gate}\n")

    agent = LinterAgent(
        source=args.source,
        namespace=args.namespace,
        manifest_path=args.path,
        profile_path=args.profile,
        provider=args.provider,
        model=args.model,
        provider_base_url=args.provider_base_url,
        provider_api_key=args.provider_api_key,
        ollama_url=args.ollama_url,
        ai_remediation=args.ai_remediation,
    )

    results = await agent.run()
    reporter = Reporter(results)

    if args.output in ("terminal", "all"):
        reporter.print_terminal()
    if args.output in ("json", "all"):
        json_out = reporter.to_json()
        if args.out_file:
            Path(args.out_file).write_text(json_out, encoding="utf-8")
            print(f"  ✔ JSON report → {args.out_file}")
        else:
            print(json_out)
    if args.output in ("markdown", "all"):
        md_out  = reporter.to_markdown()
        md_path = args.out_file or "k8s-lint-report.md"
        Path(md_path).write_text(md_out, encoding="utf-8")
        print(f"  ✔ Markdown report → {md_path}")

    gate_severities = ["critical", "high", "medium", "low"]
    gate_idx = gate_severities.index(args.severity_gate)
    blocking = [
        r for r in results.findings
        if gate_severities.index(r.severity) <= gate_idx and r.status == "fail"
    ]

    if blocking:
        print(f"\n  ✖ CI gate FAILED — {len(blocking)} blocking finding(s) at '{args.severity_gate}' or above.\n")
        return 1

    print(f"\n  ✔ CI gate PASSED — no blocking findings at '{args.severity_gate}' or above.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
