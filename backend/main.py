"""API gateway & server entrypoint for TRINETRA VoiceOps AI.

Local:   cd backend && python main.py          (http://localhost:8000)
Prod:    uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path


def _load_dotenv() -> None:
    """Tiny .env loader (no extra dependency). Real env vars always win."""
    here = Path(__file__).resolve().parent
    for candidate in (here / ".env", here.parent / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents import approve_workflow, run_swarm  # noqa: E402
from database import fetch_dashboard, init_db, reset_demo_db  # noqa: E402

HERE = Path(__file__).resolve().parent


def _frontend_index() -> Path:
    candidates = [
        os.getenv("FRONTEND_DIR"),
        HERE.parent / "frontend",   # repo layout
        HERE / "frontend",          # container layout
    ]
    for c in candidates:
        if c and (Path(c) / "index.html").is_file():
            return Path(c) / "index.html"
    raise HTTPException(status_code=500, detail="frontend/index.html not found")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="TRINETRA VoiceOps AI", version="1.0.0", lifespan=lifespan)


class VoiceCommand(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=2000)


@app.get("/")
def index():
    return FileResponse(_frontend_index(), media_type="text/html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard():
    return fetch_dashboard()


@app.post("/api/voice-command")
def voice_command(cmd: VoiceCommand):
    return run_swarm(cmd.transcript.strip())


@app.post("/api/approve/{trace_id}")
def approve(trace_id: str):
    try:
        return approve_workflow(trace_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/reset-demo")
def reset_demo():
    reset_demo_db()
    return {"status": "reset"}


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 56)
    print("  TRINETRA VoiceOps AI (Team TRINESH) is LIVE!")
    print(f"  Open in browser: http://localhost:{os.getenv('PORT', '8000')}")
    print("=" * 56 + "\n")
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
