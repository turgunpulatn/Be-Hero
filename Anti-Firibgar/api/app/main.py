import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import engine, init_db
from .routers import auth, documents, payments
from .services.analysis import recover_stuck_reviews

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    recover_stuck_reviews()
    yield


app = FastAPI(
    title="Anti-Firibgar API", version="0.1.0", lifespan=lifespan,
    docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(documents.router, prefix=PREFIX)
app.include_router(payments.router, prefix=PREFIX)


@app.get(f"{PREFIX}/health")
def health():
    status = {"api": "ok", "db": "ok", "ai_provider": settings.ai_provider, "ai": "n/a"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        status["db"] = f"error: {type(exc).__name__}"
    if settings.ai_provider == "legalai":
        base = settings.ai_base_url.rstrip("/")
        try:
            httpx.get(f"{base}/health", timeout=3).raise_for_status()
            # a made-up job id: 404 = key accepted, 401/403 = wrong key
            r = httpx.get(f"{base}/v1/jobs/healthcheck", headers={"X-API-Key": settings.ai_api_key}, timeout=3)
            status["ai"] = "ok" if r.status_code == 404 else f"error: LegalAI {r.status_code} (AI_API_KEY ni tekshiring)"
        except Exception as exc:  # noqa: BLE001
            status["ai"] = f"error: {type(exc).__name__} (LegalAI serveri ishlayaptimi? {base})"
    elif settings.ai_provider in ("ollama", "openai"):
        base = settings.ai_base_url.rstrip("/").removesuffix("/v1")
        try:
            if settings.ai_provider == "ollama":
                r = httpx.get(f"{base}/api/tags", timeout=3)
                models = [m.get("name") for m in r.json().get("models", [])]
            else:
                headers = {"Authorization": f"Bearer {settings.ai_api_key}"} if settings.ai_api_key else {}
                r = httpx.get(f"{base}/v1/models", headers=headers, timeout=3)
                models = [m.get("id") for m in r.json().get("data", [])]
            found = settings.ai_model in models or f"{settings.ai_model}:latest" in models
            status["ai"] = "ok" if found else f"model {settings.ai_model} topilmadi. Mavjud: {', '.join(models)}"
        except Exception as exc:  # noqa: BLE001
            status["ai"] = f"error: {type(exc).__name__}"
    return status
