#----original api-server-------
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
async def run_lint_stream(req: LintRequest):
    """
    SSE endpoint — streams log lines while the linter runs, then sends
    a final 'result' event with the full JSON payload.
    """
    profile_path = PROFILE_MAP.get(req.profile, req.profile)
    if not Path(profile_path).exists():
        raise HTTPException(status_code=400, detail=f"Profile not found: {profile_path}")

    async def event_stream():
        import builtins
        import re

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        ansi = re.compile(r'\x1b\[[0-9;]*m')

        original_print = builtins.print

        def capturing_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            clean = ansi.sub('', msg).strip()
            if clean:
                loop.call_soon_threadsafe(queue.put_nowait, ("log", clean))

        builtins.print = capturing_print

        async def run_agent():
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
            except Exception as e:
                queue.put_nowait(("error", str(e)))
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
            builtins.print = original_print
            task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/lint")
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
