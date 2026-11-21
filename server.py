# server.py - REST API for LegalAI (called by your web server, not by browsers directly)
#
# Run (ONE worker only: models and the job store live in this process):
#   uvicorn server:app --host 127.0.0.1 --port 8000
#
# .env:
#   LEGALAI_API_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
#   ALLOWED_IPS=203.0.113.10        # optional, comma-separated; empty = no IP filter
#   TRUSTED_PROXIES=127.0.0.1       # optional: if requests come through nginx etc., the client IP is taken
#                                   # from X-Forwarded-For / X-Real-IP, but ONLY when the request comes from these hosts
#   DEBUG_DOCS=1                   # optional, enables /docs (Swagger) for development
import hmac
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Security, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from analyze import chat_stream, analyze_contract, warmup, DISCLAIMER
from app import build_report, build_analysis_text, get_text_from_file

log = logging.getLogger("legalai.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ------------------------------------------------------------------ config
API_KEY = os.getenv("LEGALAI_API_KEY", "")
if len(API_KEY) < 32:
    raise RuntimeError("LEGALAI_API_KEY is missing or too short (need >= 32 chars). "
                       'Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"')

ALLOWED_IPS = {ip.strip() for ip in os.getenv("ALLOWED_IPS", "").split(",") if ip.strip()}
TRUSTED_PROXIES = {ip.strip() for ip in os.getenv("TRUSTED_PROXIES", "").split(",") if ip.strip()}
ALLOWED_EXT = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".txt"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
JOB_TTL_SEC = 3600          # finished jobs are kept for 1 hour
MAX_PENDING_JOBS = 10       # queued + running; beyond this -> 429


# ------------------------------------------------------------------ auth
_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _client_ip(request: Request) -> str | None:
    host = request.client.host if request.client else None
    if host and host in TRUSTED_PROXIES:
        # the right-most X-Forwarded-For entry is the one OUR proxy added (the left part can be forged by the client)
        xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if xff:
            return xff[-1]
        real = request.headers.get("x-real-ip", "").strip()
        if real:
            return real
    return host


def require_key(request: Request, key: str | None = Security(_key_header)):
    if ALLOWED_IPS and _client_ip(request) not in ALLOWED_IPS:
        raise HTTPException(403, "Forbidden")
    # constant-time comparison (no timing leaks)
    if not key or not hmac.compare_digest(key.encode(), API_KEY.encode()):
        raise HTTPException(401, "Invalid or missing API key")


# ------------------------------------------------------------------ job store
# The LLM runs on a local Ollama: one analysis at a time. Extra requests wait in the queue.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analyze")
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


class EmptyTextError(Exception):
    pass


# Same contract text -> same report (analysis is deterministic), so repeat submissions are free.
_cache: dict[str, tuple[float, dict]] = {}
CACHE_MAX = 50


def _cache_key(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def _cache_get(key: str):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < JOB_TTL_SEC:
            return hit[1]
        _cache.pop(key, None)
    return None


def _cache_put(key: str, payload: dict):
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))   # drop the oldest
        _cache[key] = (time.time(), payload)


def _cleanup_jobs():
    now = time.time()
    with _lock:
        for jid in [j for j, v in _jobs.items()
                    if v["finished"] and now - v["finished"] > JOB_TTL_SEC]:
            del _jobs[jid]


def _pending_count_unlocked() -> int:
    return sum(1 for v in _jobs.values() if v["status"] in ("queued", "running"))


def _update(job: dict, **fields):
    with _lock:
        job.update(fields)


def _run_job(job_id: str, text: str | None, filepath: str | None):
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"
    t0 = time.time()

    def progress(msg):
        with _lock:
            job["progress"].append({"t": round(time.time() - t0, 1), "msg": msg})

    try:
        if filepath:
            progress("Matn oʻqilmoqda...")
            text = get_text_from_file(filepath)
        if not text or not text.strip():
            raise EmptyTextError()
        key = _cache_key(text)
        payload = _cache_get(key)
        if payload:
            progress("Natija keshdan olindi.")
        else:
            result = analyze_contract(text, progress=progress)
            report = build_report(result)
            payload = {
                "result": {
                    "verdict": report["verdict"],            # {level: high|medium|low|clean|unknown, label, summary}
                    "risks": report["risks"],                # flat, sorted high -> low, same numbering as the terminal
                    "actions": report["actions"],            # ordered action plan
                    "suggested_questions": report["questions"],
                    "coverage": report["coverage"],          # how much of the document was scanned
                    "warnings": result.get("ogohlantirish", []),
                    "disclaimer": result.get("disclaimer", DISCLAIMER),
                    "raw": {k: v for k, v in result.items() if k != "tahlil_matni"},
                },
                "analysis_text": build_analysis_text(result),
                "document_text": result.get("tahlil_matni", text),   # cleaned (Latin) text
            }
            # do not cache incomplete analyses (some chunk failed) - let the user retry them
            if not any("tahlil qilinmadi" in w for w in payload["result"]["warnings"]):
                _cache_put(key, payload)
        _update(job, result=payload["result"], document_text=payload["document_text"],
                analysis_text=payload["analysis_text"], status="done")
    except EmptyTextError:
        _update(job, status="error", error={"code": "empty_text", "message": "No text could be extracted from the file."})
    except Exception:
        log.exception("Job %s failed", job_id)   # details only in the server log, not to the client
        _update(job, status="error", error={"code": "internal_error", "message": "Analysis failed."})
    finally:
        _update(job, elapsed=round(time.time() - t0, 1), finished=time.time())
        if filepath:
            try:
                os.remove(filepath)
            except OSError:
                pass


def _submit(text: str | None = None, filepath: str | None = None) -> str:
    _cleanup_jobs()
    job_id = uuid.uuid4().hex
    with _lock:   # check + insert atomically, so two parallel requests cannot both pass the limit
        full = _pending_count_unlocked() >= MAX_PENDING_JOBS
        if not full:
            _jobs[job_id] = {
                "status": "queued", "progress": [], "result": None, "error": None,
                "document_text": None, "analysis_text": None,
                "created": time.time(), "finished": None, "elapsed": None,
            }
    if full:
        if filepath:
            os.remove(filepath)
        raise HTTPException(429, "Queue is full, try again later", headers={"Retry-After": "60"})
    _executor.submit(_run_job, job_id, text, filepath)
    return job_id


# ------------------------------------------------------------------ schemas
class AnalyzeTextRequest(BaseModel):
    text: str = Field(min_length=20, max_length=MAX_TEXT_CHARS)


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class Doc(BaseModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    analysis: str = Field("", max_length=10_000)   # = "analysis_text" from the job result


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = Field(default_factory=list, max_length=10)
    doc: Doc | None = None        # either pass the document explicitly...
    job_id: str | None = None     # ...or reference a finished analysis job (kept for 1 hour)


def _job_snapshot(job_id: str) -> dict | None:
    """A consistent copy of a job (the worker thread may be changing it right now)."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        snap = dict(job)
        snap["progress"] = list(job["progress"])
        return snap


def _resolve_doc(req: ChatRequest) -> dict | None:
    if req.doc:
        return {"text": req.doc.text, "analysis": req.doc.analysis}
    if req.job_id:
        job = _job_snapshot(req.job_id)
        if not job:
            raise HTTPException(404, "job_id not found or expired; pass 'doc' explicitly")
        if job["status"] != "done":
            raise HTTPException(409, "Analysis is not finished yet")
        res = job["result"]
        return {"text": job["document_text"], "analysis": job["analysis_text"],
                "risks": res.get("risks", []), "verdict": res.get("verdict")}
    return None


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=warmup, daemon=True).start()   # preload models
    yield
    _executor.shutdown(wait=False, cancel_futures=True)


_debug = os.getenv("DEBUG_DOCS") == "1"
app = FastAPI(
    title="LegalAI API", version="1.0",
    lifespan=lifespan,
    docs_url="/docs" if _debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _debug else None,
)


@app.get("/health")
def health():
    return {"status": "ok"}


v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_key)])


@v1.post("/analyze/text", status_code=202)
def analyze_text(body: AnalyzeTextRequest):
    """Start an analysis of plain text. Returns job_id immediately."""
    return {"job_id": _submit(text=body.text), "status": "queued"}


@v1.post("/analyze/file", status_code=202)
def analyze_file(file: UploadFile = File(...)):
    """Start an analysis of an uploaded .pdf/.jpg/.png/.txt. Returns job_id immediately."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXT))}")

    # random temp name: the client-supplied filename is never used on disk
    fd, path = tempfile.mkstemp(suffix=ext)
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                out.write(chunk)
    except Exception:
        os.remove(path)
        raise
    if size == 0:
        os.remove(path)
        raise HTTPException(400, "Empty file")
    return {"job_id": _submit(filepath=path), "status": "queued"}


@v1.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Poll this every 2-3 s. status: queued | running | done | error."""
    job = _job_snapshot(job_id)
    if not job:
        raise HTTPException(404, "Job not found or expired")
    out = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "elapsed": job["elapsed"] if job["finished"] else round(time.time() - job["created"], 1),
    }
    if job["status"] == "done":
        out["result"] = job["result"]
        out["document_text"] = job["document_text"]   # keep these two if you want to
        out["analysis_text"] = job["analysis_text"]   # pass them back as "doc" in /chat
    elif job["status"] == "error":
        out["error"] = job["error"]
    return out


@v1.post("/chat")
def chat(body: ChatRequest):
    """Full answer in one JSON response (can take 10-60 s on a 7B model)."""
    doc = _resolve_doc(body)
    history = [(t.role, t.content) for t in body.history]
    answer = "".join(chat_stream(body.question, history, doc))
    return {"answer": answer}


@v1.post("/chat/stream")
def chat_sse(body: ChatRequest):
    """Server-Sent Events: each event is data: {"t": "<piece of text>"}; the end is `event: done`."""
    doc = _resolve_doc(body)
    history = [(t.role, t.content) for t in body.history]

    def gen():
        for piece in chat_stream(body.question, history, doc):
            yield f"data: {json.dumps({'t': piece}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(v1)