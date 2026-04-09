"""
FastAPI server — exposes the K8s linter engine as an HTTP API.

Install deps:  pip install fastapi uvicorn
Run:           uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.linter_agent import LinterAgent
from output.reporter import Reporter

import io
import contextlib


logging.basicConfig(level=logging.INFO)
app = FastAPI(title="K8s Linter API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request model ─────────────────────────────────────────────────────────────

class LintRequest(BaseModel):
    source:            str  = Field("cluster")
    namespace:         str  = Field("default")
    manifest_path:     str  = Field("./manifests")
    profile:           str  = Field("profiles/custom.yaml")
    provider:          str  = Field("ollama")
    model:             str  = Field("")
    ollama_url:        str  = Field("http://192.168.0.7:11434")
    provider_base_url: str  = Field("")
    provider_api_key:  str  = Field("")
    ai_remediation:    bool = Field(False)


PROFILE_MAP = {
    "cis":    "profiles/cis-benchmark.yaml",
    "custom": "profiles/custom.yaml",
}



class SSELoggingHandler(logging.Handler):
    def __init__(self, loop, queue):
        super().__init__()
        self.loop = loop
        self.queue = queue

    def emit(self, record):
        log_entry = self.format(record)
        # Thread-safe push to the async queue
        self.loop.call_soon_threadsafe(self.queue.put_nowait, ("log", log_entry))

class UniversalStream(io.TextIOBase):
    def __init__(self, loop, queue):
        self.loop = loop
        self.queue = queue
    def write(self, s):
        if s.strip():
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("log", s.strip()))
        return len(s)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def serve_ui():
    html_path = Path("k8s_environment_linter.html")
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI file not found")
    return FileResponse(html_path, media_type="text/html")


@app.get("/api/profiles")
def list_profiles():
    profiles_dir = Path("profiles")
    profiles = [
        {"value": str(p), "label": p.stem.replace("-", " ").replace("_", " ").title()}
        for p in sorted(profiles_dir.glob("*.yaml"))
    ]
    return {"profiles": profiles}


@app.post("/api/lint/stream")
async def run_lint_stream(
    source: str = "cluster",
    namespace: str = "default",
    manifest_path: str = "./manifests",
    profile: str = "profiles/custom.yaml",
    provider: str = "ollama",
    ai_remediation: bool = True
):
    # Resolve the profile path
    profile_path = PROFILE_MAP.get(profile, profile)

    async def event_stream():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        # Bridge for logging.info()
        class SSEHandler(logging.Handler):
            def emit(self, record):
                msg = self.format(record)
                loop.call_soon_threadsafe(queue.put_nowait, ("log", msg))

        # handler = SSEHandler(loop, queue)
        handler = SSEHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(handler)

        try:
            task = asyncio.create_task(run_agent())
            while True:
                event_type, data = await queue.get()
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                if event_type in ("done", "error"):
                    break
        finally:
            logging.getLogger().removeHandler(handler)   # always cleaned up
            task.cancel()

        async def run_agent():
            # Bridge for print()
            with contextlib.redirect_stdout(UniversalStream(loop, queue)):
                try:
                    # Pass all 4 required positional arguments
                    agent = LinterAgent(
                        source,          # 1
                        namespace,       # 2
                        manifest_path,   # 3
                        profile_path,    # 4
                        provider=provider,
                        ai_remediation=ai_remediation
                    )
                    results = await agent.run()
                    queue.put_nowait(("result", Reporter(results).to_json()))
                except Exception as e:
                    queue.put_nowait(("error", str(e)))
                finally:
                    logging.getLogger().removeHandler(handler)
                    queue.put_nowait(("done", ""))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/lint")
async def run_lint(req: LintRequest):
    """Non-streaming fallback — returns full JSON result."""
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    reporter = Reporter(results)
    return json.loads(reporter.to_json())

@app.get("/api/namespaces")
async def list_namespaces():
    import subprocess, json
    try:
        result = subprocess.run(
            ["kubectl", "get", "namespaces", "-o", "json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            names = [item["metadata"]["name"] for item in data.get("items", [])]
            return {"namespaces": names}
    except Exception:
        pass
    return {"namespaces": ["default"]}   # fallback

# @app.get("/api/cluster")
# async def list_cluster():
#     import subprocess, json
#     try:
#         result = subprocess.run(
#             ["kubectl", "config", "namespaces", "-o", "json"],
#             capture_output=True, text=True, timeout=10
#         )
#         if result.returncode == 0:
#             data = json.loads(result.stdout)
#             names = [item["metadata"]["name"] for item in data.get("items", [])]
#             return {"namespaces": names}
#     except Exception:
#         pass
#     return {"namespaces": ["default"]}     