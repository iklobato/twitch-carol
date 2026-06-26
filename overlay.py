from __future__ import annotations

import logging

from fastapi import WebSocket, WebSocketDisconnect

from alerts import StreamAlert

logger = logging.getLogger(__name__)


class OverlayHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, socket: WebSocket) -> None:
        await socket.accept()
        self._connections.add(socket)
        logger.info("overlay connected (%d total)", len(self._connections))

    def disconnect(self, socket: WebSocket) -> None:
        self._connections.discard(socket)
        logger.info("overlay disconnected (%d total)", len(self._connections))

    async def broadcast(self, alert: StreamAlert) -> None:
        payload = alert.to_payload()
        logger.info("alert -> overlay: %s", payload)
        dead: list[WebSocket] = []
        for socket in self._connections:
            try:
                await socket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(socket)
        for socket in dead:
            self.disconnect(socket)
