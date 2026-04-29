"""
FastAPI server — K8s Linter API v2.1

New in v2.1:
  - /api/users  GET/POST/PUT/DELETE — user management (JSON-file backed)
  - /api/auth/login — credential check
  - Client-disconnect cancellation on /api/lint/stream
  - Graceful provider-package detection (clear error if openai/anthropic not installed)

Run: uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import logging
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.linter_agent import LinterAgent
from output.reporter import Reporter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="K8s Linter API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

PROFILE_MAP = {
    "cis":           "profiles/cis-benchmark.yaml",
    "cis-benchmark": "profiles/cis-benchmark.yaml",
    "nsa":           "profiles/nsa-hardening.yaml",
    "nsa-hardening": "profiles/nsa-hardening.yaml",
    "custom":        "profiles/custom.yaml",
}

# JSON-file user store — swap for a real DB in production
USERS_FILE = Path("users.json")


# ── Provider package detection ────────────────────────────────────────

def _pkg_installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


PROVIDER_PACKAGES = {
    "openai":        "openai",
    "openai-compat": "openai",
    "anthropic":     "anthropic",
    # ollama, mock, custom don't need extra packages
}


def _check_provider_deps(provider: str) -> str | None:
    """Return an install hint string if the required package is missing, else None."""
    pkg = PROVIDER_PACKAGES.get(provider)
    if pkg and not _pkg_installed(pkg):
        return f"Package '{pkg}' is not installed. Run: pip install {pkg}"
    return None


# ── User store ────────────────────────────────────────────────────────

def _load_users() -> list[dict]:
    if not USERS_FILE.exists():
        default = [
            {"username": "admin",  "password": "admin123", "role": "admin",    "active": True},
            {"username": "demo",   "password": "demo",     "role": "viewer",   "active": True},
            {"username": "k8s",    "password": "linter",   "role": "operator", "active": True},
        ]
        _save_users(default)
        return default
    return json.loads(USERS_FILE.read_text())


def _save_users(users: list[dict]) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2))


# ── Pydantic models ───────────────────────────────────────────────────

class LintRequest(BaseModel):
    source:            str  = Field("cluster")
    namespace:         str  = Field("default")
    manifest_path:     str  = Field("./manifests")
    profile:           str  = Field("custom")
    provider:          str  = Field("ollama")
    model:             str  = Field("llama3")
    ollama_url:        str  = Field("http://localhost:11434")
    provider_base_url: str  = Field("")
    provider_api_key:  str  = Field("")
    ai_remediation:    bool = Field(False)


class UserCreate(BaseModel):
    username: str
    password: str
    role:     Literal["admin", "operator", "viewer"] = "viewer"


class UserUpdate(BaseModel):
    password: str | None = None
    role:     Literal["admin", "operator", "viewer"] | None = None
    active:   bool | None = None


class UniversalStream(io.TextIOBase):
    """Bridges print() output into the SSE queue."""
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self.loop  = loop
        self.queue = queue

    def write(self, s: str) -> int:
        if s.strip():
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("log", s.strip()))
        return len(s)

    def flush(self): pass


# ── UI ────────────────────────────────────────────────────────────────

@app.get("/")
def serve_ui():
    html_path = Path("k8s_linter_ui.html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI file not found: k8s_linter_ui.html")
    return FileResponse(html_path, media_type="text/html")


# ── System ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0"}


@app.get("/api/profiles")
def list_profiles():
    # Human-readable labels for known profiles
    LABELS = {
        "cis-benchmark": "CIS Benchmark",
        "nsa-hardening": "NSA Hardening",
        "custom":        "Custom",
    }
    profiles_dir = Path("profiles")
    if not profiles_dir.exists():
        return {"profiles": [{"value": "custom", "label": "Custom"}]}
    return {"profiles": [
        {
            "value": p.stem,
            "label": LABELS.get(p.stem, p.stem.replace("-", " ").replace("_", " ").title()),
        }
        for p in sorted(profiles_dir.glob("*.yaml"))
    ]}


@app.get("/api/namespaces")
def list_namespaces():
    try:
        result = subprocess.run(
            ["kubectl", "get", "namespaces", "--output=json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data  = json.loads(result.stdout)
            names = [item["metadata"]["name"] for item in data.get("items", [])]
            return {"namespaces": names}
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return {"namespaces": ["default"]}


@app.get("/api/ollama/models")
async def list_ollama_models(url: str = "http://localhost:11434"):
    """Proxy Ollama /api/tags to avoid browser CORS issues (no extra packages needed)."""
    import urllib.request, urllib.error, json as _json
    target = url.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(target, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
            return {"models": [m["name"] for m in data.get("models", [])]}
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama at {url}: {exc.reason}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama error: {exc}")


@app.get("/api/providers")
def list_providers():
    """Return all providers with availability status based on installed packages."""
    providers = [
        {"id": "ollama",        "label": "Ollama (local)",    "available": True},
        {"id": "openai",        "label": "OpenAI",            "available": _pkg_installed("openai")},
        {"id": "openai-compat", "label": "OpenAI-compatible", "available": _pkg_installed("openai")},
        {"id": "anthropic",     "label": "Anthropic",         "available": _pkg_installed("anthropic")},
        {"id": "mock",          "label": "Mock (dry-run)",     "available": True},
    ]
    return {"providers": providers}


# ── User management ───────────────────────────────────────────────────

@app.get("/api/users")
def get_users():
    users = _load_users()
    return {"users": [{k: v for k, v in u.items() if k != "password"} for u in users]}


@app.post("/api/users", status_code=201)
def create_user(body: UserCreate):
    users = _load_users()
    if any(u["username"] == body.username for u in users):
        raise HTTPException(status_code=409, detail=f"User '{body.username}' already exists")
    users.append({"username": body.username, "password": body.password, "role": body.role, "active": True})
    _save_users(users)
    return {"username": body.username, "role": body.role, "active": True}


@app.put("/api/users/{username}")
def update_user(username: str, body: UserUpdate):
    users = _load_users()
    for u in users:
        if u["username"] == username:
            if body.password is not None: u["password"] = body.password
            if body.role     is not None: u["role"]     = body.role
            if body.active   is not None: u["active"]   = body.active
            _save_users(users)
            return {k: v for k, v in u.items() if k != "password"}
    raise HTTPException(status_code=404, detail=f"User '{username}' not found")


@app.delete("/api/users/{username}", status_code=204)
def delete_user(username: str):
    users     = _load_users()
    remaining = [u for u in users if u["username"] != username]
    if len(remaining) == len(users):
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    _save_users(remaining)


@app.post("/api/auth/login")
def login(body: dict):
    username = body.get("username", "")
    password = body.get("password", "")
    users    = _load_users()
    user     = next((u for u in users if u["username"] == username and u["active"]), None)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": user["username"], "role": user["role"]}


# ── Lint — streaming ──────────────────────────────────────────────────

@app.post("/api/lint/stream")
async def run_lint_stream(req: LintRequest, request: Request):
    """
    SSE endpoint — streams log lines, then emits one 'result' event.

    Improvements in v2.1:
      - Provider package check BEFORE starting agent (clear error instead of warning)
      - Client-disconnect cancellation via asyncio.wait
    """
    # ── 1. Profile check ──────────────────────────────────────────────
    profile_path = PROFILE_MAP.get(req.profile, req.profile)
    if not Path(profile_path).exists():
        raise HTTPException(
            status_code=400,
            detail=f"Profile not found: {profile_path}. Available: {list(PROFILE_MAP.keys())}"
        )

    # ── 2. Provider package check — fail fast with a clear message ────
    if req.ai_remediation:
        missing = _check_provider_deps(req.provider)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"AI remediation requested but provider package missing. {missing}"
            )

    async def event_stream():
        loop  = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        class SSEHandler(logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                loop.call_soon_threadsafe(queue.put_nowait, ("log", msg))

        handler = SSEHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        async def run_agent():
            with contextlib.redirect_stdout(UniversalStream(loop, queue)):
                try:
                    agent = LinterAgent(
                        source=req.source,
                        namespace=req.namespace,
                        manifest_path=req.manifest_path,
                        profile_path=profile_path,
                        provider=req.provider,
                        model=req.model,
                        ollama_url=req.ollama_url,
                        provider_base_url=req.provider_base_url,
                        provider_api_key=req.provider_api_key,
                        ai_remediation=req.ai_remediation,
                    )
                    results  = await agent.run()
                    reporter = Reporter(results)
                    queue.put_nowait(("result", reporter.to_json()))
                except Exception as exc:
                    logger.exception("Lint agent error")
                    queue.put_nowait(("error", str(exc)))
                finally:
                    queue.put_nowait(("done", ""))

        task = asyncio.create_task(run_agent())

        try:
            while True:
                disconnect_task = asyncio.create_task(request.is_disconnected())
                queue_task      = asyncio.create_task(queue.get())

                done, pending = await asyncio.wait(
                    {disconnect_task, queue_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

                if disconnect_task in done and await disconnect_task:
                    logger.info("Client disconnected — cancelling audit")
                    task.cancel()
                    break

                if queue_task in done:
                    event_type, data = queue_task.result()
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                    if event_type in ("done", "error"):
                        break

        except asyncio.CancelledError:
            pass
        finally:
            root_logger.removeHandler(handler)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ── Lint — non-streaming fallback ─────────────────────────────────────

@app.post("/api/lint")
async def run_lint(req: LintRequest):
    profile_path = PROFILE_MAP.get(req.profile, req.profile)
    if not Path(profile_path).exists():
        raise HTTPException(status_code=400, detail=f"Profile not found: {profile_path}")

    if req.ai_remediation:
        missing = _check_provider_deps(req.provider)
        if missing:
            raise HTTPException(status_code=422, detail=missing)

    agent = LinterAgent(
        source=req.source, namespace=req.namespace, manifest_path=req.manifest_path,
        profile_path=profile_path, provider=req.provider, model=req.model,
        ollama_url=req.ollama_url, provider_base_url=req.provider_base_url,
        provider_api_key=req.provider_api_key, ai_remediation=req.ai_remediation,
    )
    try:
        results = await agent.run()
    except Exception as exc:
        logger.exception("Lint agent error")
        raise HTTPException(status_code=500, detail=str(exc))

    return json.loads(Reporter(results).to_json())
