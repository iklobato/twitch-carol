from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from config import Settings
from livepix import LivePixAlertService, LivePixWebhookEvent
from overlay import OverlayHub

OVERLAY_HTML = (Path(__file__).parent / "overlay.html").read_text(encoding="utf-8")


def build_app(
    hub: OverlayHub, alerts: LivePixAlertService, settings: Settings
) -> FastAPI:
    app = FastAPI(title="Twitch Live Manager")

    @app.get("/overlay", response_class=HTMLResponse)
    async def overlay() -> str:
        return OVERLAY_HTML

    @app.websocket("/ws")
    async def overlay_socket(socket: WebSocket) -> None:
        await hub.connect(socket)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(socket)

    @app.post("/webhook/livepix/{secret}")
    async def livepix_webhook(secret: str, request: Request) -> dict:
        if not hmac.compare_digest(secret, settings.livepix_webhook_secret):
            raise HTTPException(status_code=403, detail="bad webhook secret")
        event = LivePixWebhookEvent.model_validate(await request.json())
        await alerts.handle(event)
        return {"ok": True}

    return app
