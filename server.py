"""
FastAPI server — exposes the K8s linter engine as an HTTP API.

Install:  pip install fastapi uvicorn
Run:      uvicorn server:app --reload --port 8000
UI:       place k8s_linter_ui.html in same directory, open http://localhost:8000
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.linter_agent import LinterAgent
from output.reporter import Reporter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="K8s Linter API", version="2.0.0")

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


@app.get("/")
def serve_ui():
    html_path = Path("k8s_linter_ui.html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI file not found: k8s_linter_ui.html")
    return FileResponse(html_path, media_type="text/html")


@app.get("/api/profiles")
def list_profiles():
    """Return available profile files from the profiles/ directory."""
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
    """Return Kubernetes namespaces from the live cluster via kubectl."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "namespaces", "--output=json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            data   = json.loads(result.stdout)
            names  = [item["metadata"]["name"] for item in data.get("items", [])]
            return {"namespaces": names}
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return {"namespaces": ["default"]}


@app.post("/api/lint/stream")
async def run_lint_stream(req: LintRequest):
    """
    Server-Sent Events endpoint — streams log lines while the audit runs,
    then emits a single 'result' event with the full JSON report.
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
            """Forwards logging.info() / warning() lines into the SSE queue."""
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
                event_type, data = await queue.get()
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                if event_type in ("done", "error"):
                    break
        finally:
            root_logger.removeHandler(handler)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/api/lint")
async def run_lint(req: LintRequest):
    """Non-streaming fallback — returns the full JSON report in one response."""
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


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
