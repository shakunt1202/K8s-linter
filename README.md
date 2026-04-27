# K8s Linter v2.1

AI-powered Kubernetes security & compliance auditor with a real-time streaming UI.

---

## Project Structure

```
k8s-linter/
│
├── k8s_linter_ui.html          # Single-file frontend (self-contained)
├── server.py                   # FastAPI app — all routes
├── main.py                     # CLI entry point
├── requirements.txt            # All deps (including AI providers)
├── requirements-minimal.txt    # Core only (Ollama, no openai/anthropic)
│
├── frontend/                   # Source JS/CSS modules (reference / split if needed)
│   ├── js/
│   │   ├── auth.js             # Login, logout, session, user-store
│   │   ├── tokens.js           # AI provider key storage & modal
│   │   ├── ui.js               # Findings render, scores, env state, tabs
│   │   └── audit.js            # Run/stop audit, SSE, server checks
│   └── css/
│       └── theme.css           # CSS variables & base styles
│
├── agent/                      # Lint orchestration
│   ├── linter_agent.py         # Main agent — wires sources → engine → AI
│   └── providers/
│       ├── __init__.py         # BaseProvider, registry (get_provider)
│       ├── anthropic_provider.py
│       ├── openai_provider.py
│       ├── ollama_provider.py
│       └── mock_provider.py
│
├── api/                        # (future) split routes here
│   ├── lint.py
│   ├── users.py
│   └── system.py
│
├── auth/                       # (future) real DB / JWT auth
│   └── store.py
│
├── checks/
│   └── engine.py               # JSONPath check evaluator
│
├── models.py                   # CheckRule, Finding, AuditResults, etc.
│
├── output/
│   └── reporter.py             # Terminal / JSON / Markdown formatters
│
├── profiles/
│   ├── loader.py
│   ├── custom.yaml
│   ├── cis-benchmark.yaml
│   └── nsa-hardening.yaml
│
├── sources/
│   ├── cluster_source.py       # kubectl-backed resource fetcher
│   └── manifest_source.py      # Local YAML/Helm manifest loader
│
├── tests/
│   └── test_engine.py
│
├── users.json                  # Auto-created on first run (user store)
└── oldUI/                      # Legacy UI kept for reference
```

---

## Quick Start

```bash
# 1. Install core dependencies
pip install -r requirements-minimal.txt

# 2. For AI remediation with a cloud provider:
pip install anthropic    # for Anthropic Claude
pip install openai       # for OpenAI / Azure / Groq / Together

# 3. Start server
uvicorn server:app --reload --port 8000

# 4. Open UI
open http://localhost:8000
```

Default credentials: `admin / admin123` · `demo / demo` · `k8s / linter`

---

## What's Fixed in v2.1

### UI bugs resolved
| Bug | Fix |
|-----|-----|
| User avatar invisible / blended into background | Avatar uses explicit hex gradient (`#5b7fff → #a78bfa`) instead of CSS vars that were undefined. Dark mode variant also explicit. |
| Manage Users / Logout buttons didn't work | `toggleUserMenu(e)` now calls `e.stopPropagation()` so the global click-outside listener doesn't close it before the modal opens. Logout directly calls `handleLogout()` which bypasses the broken `doLogout()` reference. |
| Prod/Stage/Dev showed same results | `envState` object correctly isolated per environment. Each `UI.setEnv()` call restores that env's stored findings, scores, AI summary and gate result. Empty envs show `—` not stale data from another env. |
| Dark mode dropdowns washed out | `select` gets `background-color: var(--select-bg) !important` and `color: var(--select-text) !important`. `--select-bg: #1a1f2e` in dark, `#ffffff` in light. `select option` gets matching background/color. |

### Server improvements
| Issue | Fix |
|-------|-----|
| `WARNING: AI remediation failed for X (openai): openai package not installed` | `server.py` now calls `_check_provider_deps()` BEFORE starting the agent. If `openai` / `anthropic` isn't installed, the request returns HTTP 422 with a clear message: *"Package 'openai' is not installed. Run: pip install openai"*. The warning in agent logs is now gone. |
| No way to stop a running audit server-side | Client disconnect detected via `asyncio.wait({disconnect_task, queue_task})` — when browser aborts, the backend task is cancelled cleanly. |

---

## AI Provider Setup

| Provider | Package | Key field |
|----------|---------|-----------|
| Ollama (local) | none | Ollama server URL |
| OpenAI | `pip install openai` | `OPENAI_API_KEY` or UI key field |
| Anthropic | `pip install anthropic` | `ANTHROPIC_API_KEY` or UI key field |
| Azure OpenAI | `pip install openai` | Azure endpoint + key |
| Groq / Together / LM Studio | `pip install openai` | custom base URL + key |

Keys entered in the UI **AI API Keys** modal are stored in `localStorage` and sent per-request. They are never logged or written to disk by the server.

---

## User Roles

| Role | Permissions |
|------|-------------|
| `admin` | Run audits, manage users, configure AI keys |
| `operator` | Run audits, configure AI keys |
| `viewer` | View results only (audit button still shown; role enforcement is server-side in production) |

> **Note:** The current implementation uses `localStorage` for the user store (demo mode). For production, replace `_load_users()` / `_save_users()` in `server.py` with a proper database and add JWT token auth.
