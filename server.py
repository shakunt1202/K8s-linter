"""
FastAPI server — exposes the K8s linter engine as an HTTP API.

Install:  pip install fastapi uvicorn
Run:      uvicorn server:app --reload --port 8000
UI:       place k8s_linter_ui.html in same directory, open http://localhost:8000

New in v2.1:
 - /api/users          GET/POST/PUT/DELETE  — user management (demo: JSON-file backed)
 - Provider API key forwarding  (openai / anthropic / azure / custom)
 - Client-disconnect cancellation on /api/lint/stream
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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

PROFILE_MAP = {
    "cis":    "profiles/cis-benchmark.yaml",
    "nsa":    "profiles/nsa-hardening.yaml",
    "custom": "profiles/custom.yaml",
}

# Simple JSON-file user store — swap for a real DB in production
USERS_FILE = Path("users.json")


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


# ── Pydantic models ────────────────────────────────────────────────────

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

    def flush(self):
        pass


# ── Static / UI ───────────────────────────────────────────────────────

@app.get("/")
def serve_ui():
    html_path = Path("k8s_linter_ui.html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI file not found: k8s_linter_ui.html")
    return FileResponse(html_path, media_type="text/html")


# ── Profiles & Namespaces ─────────────────────────────────────────────

@app.get("/api/profiles")
def list_profiles():
    profiles_dir = Path("profiles")
    if not profiles_dir.exists():
        return {"profiles": [{"value": "custom", "label": "Custom"}]}
    profiles = [
        {
            "value": p.stem,
            "label": p.stem.replace("-", " ").replace("_", " ").title(),
            "path":  str(p),
        }
        for p in sorted(profiles_dir.glob("*.yaml"))
    ]
    return {"profiles": profiles}


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


# ── User management ───────────────────────────────────────────────────

@app.get("/api/users")
def get_users():
    """Return all users (passwords redacted)."""
    users = _load_users()
    return {"users": [
        {k: v for k, v in u.items() if k != "password"}
        for u in users
    ]}


@app.post("/api/users", status_code=201)
def create_user(body: UserCreate):
    users = _load_users()
    if any(u["username"] == body.username for u in users):
        raise HTTPException(status_code=409, detail=f"User '{body.username}' already exists")
    users.append({
        "username": body.username,
        "password": body.password,
        "role":     body.role,
        "active":   True,
    })
    _save_users(users)
    return {"username": body.username, "role": body.role, "active": True}


@app.put("/api/users/{username}")
def update_user(username: str, body: UserUpdate):
    users = _load_users()
    for u in users:
        if u["username"] == username:
            if body.password is not None:
                u["password"] = body.password
            if body.role is not None:
                u["role"] = body.role
            if body.active is not None:
                u["active"] = body.active
            _save_users(users)
            return {k: v for k, v in u.items() if k != "password"}
    raise HTTPException(status_code=404, detail=f"User '{username}' not found")


@app.delete("/api/users/{username}", status_code=204)
def delete_user(username: str):
    users = _load_users()
    remaining = [u for u in users if u["username"] != username]
    if len(remaining) == len(users):
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    _save_users(remaining)


@app.post("/api/auth/login")
def login(body: dict):
    """Simple credential check — returns role on success."""
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
    Server-Sent Events endpoint — streams log lines while the audit runs,
    then emits a single 'result' event with the full JSON report.

    Supports:
      - Client disconnect: the SSE generator watches `await request.is_disconnected()`
      - Provider API keys forwarded from UI (provider_api_key / provider_base_url)
    """
    profile_path = PROFILE_MAP.get(req.profile, req.profile)
    if not Path(profile_path).exists():
        raise HTTPException(
            status_code=400,
            detail=f"Profile not found: {profile_path}. Available: {list(PROFILE_MAP.keys())}"
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
                    results = await agent.run()
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
                # Poll for client disconnect alongside queue items
                disconnect_task = asyncio.create_task(request.is_disconnected())
                queue_task      = asyncio.create_task(queue.get())

                done, pending = await asyncio.wait(
                    {disconnect_task, queue_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel the losing task
                for t in pending:
                    t.cancel()

                if disconnect_task in done and await disconnect_task:
                    logger.info("Client disconnected — cancelling audit")
                    task.cancel()
                    break

                event_type, data = await queue_task if queue_task in done else (None, None)
                if event_type is None:
                    # queue_task was in pending (cancelled), loop again
                    continue

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
    try:
        results = await agent.run()
    except Exception as exc:
        logger.exception("Lint agent error")
        raise HTTPException(status_code=500, detail=str(exc))

    return json.loads(Reporter(results).to_json())


# ── Health ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0"}