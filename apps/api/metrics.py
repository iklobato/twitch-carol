"""Prometheus /metrics for the API: automatic HTTP metrics (request rate,
latency, in-progress, status classes) exposed behind a bearer token so only
the monitoring box can scrape it. Pipeline backlog and DB/host metrics come
from the valkey/postgres/node exporters, not from here."""

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from core.config import get_settings


def setup_metrics(app: FastAPI) -> None:
    Instrumentator(excluded_handlers=["/metrics", "/healthz"]).instrument(app)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        token = get_settings().metrics_token
        expected = f"Bearer {token}"
        # No token configured means the endpoint stays closed, never open.
        if not token or request.headers.get("authorization") != expected:
            raise HTTPException(status_code=404)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
