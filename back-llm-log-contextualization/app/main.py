from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.config.settings import settings
from app.database.db import close_db, init_db
from app.services.metrics_service import MetricsService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    metrics = MetricsService()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_tracing(request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid4()))
        started = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        metrics.record(request.url.path, response.status_code, duration_ms)
        return response

    @app.get("/metrics", summary="Prometheus-compatible metrics")
    async def metrics_endpoint() -> Response:
        return Response(content=metrics.render_prometheus(), media_type="text/plain; version=0.0.4")

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
