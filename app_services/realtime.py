import json
import logging
import time
from typing import Dict, List

from fastapi import WebSocket


QUIET_ACCESS_PATHS = {
    "/api/queue_status",
    "/api/canvases",
    "/api/canvases/trash",
}
QUIET_ACCESS_PREFIXES = (
    "/api/canvases/",
)


class QuietAccessLogFilter(logging.Filter):
    def filter(self, record):
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 3:
            path = str(args[2]).split("?", 1)[0]
            status = int(args[4]) if len(args) >= 5 and str(args[4]).isdigit() else 0
            quiet_dynamic = any(path.startswith(prefix) and path.endswith("/meta") for prefix in QUIET_ACCESS_PREFIXES)
            if (path in QUIET_ACCESS_PATHS or quiet_dynamic) and status < 400:
                return False
        message = record.getMessage()
        if any(f'"GET {path}' in message and '" 200' in message for path in QUIET_ACCESS_PATHS):
            return False
        if 'GET /api/canvases/' in message and '/meta' in message and '" 200' in message:
            return False
        return True


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_connections: Dict[str, WebSocket] = {}
        self.connection_clients: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, client_id: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connection_clients[websocket] = client_id or f"anon-{id(websocket)}"
        if client_id:
            self.user_connections[client_id] = websocket
        print(f"WS Connected. Total: {len(self.active_connections)}, Online: {self.online_count()}")
        await self.broadcast_count()

    async def disconnect(self, websocket: WebSocket, client_id: str = None):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.connection_clients.pop(websocket, None)
        if client_id and self.user_connections.get(client_id) is websocket:
            del self.user_connections[client_id]
        print(f"WS Disconnected. Total: {len(self.active_connections)}, Online: {self.online_count()}")
        await self.broadcast_count()

    def online_count(self):
        visible_clients = {
            client_id for client_id in self.connection_clients.values()
            if client_id and not str(client_id).startswith("canvas_")
        }
        return len(visible_clients)

    async def broadcast_count(self):
        count = self.online_count()
        data = json.dumps({"type": "stats", "online_count": count})
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(data)
            except Exception as exc:
                print(f"Broadcast error: {exc}")
                self.active_connections.remove(connection)

    async def broadcast_new_image(self, image_data: dict):
        data = json.dumps({"type": "new_image", "data": image_data})
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(data)
            except Exception as exc:
                print(f"Broadcast image error: {exc}")
                self.active_connections.remove(connection)

    async def broadcast_canvas_updated(self, canvas_id: str, updated_at: int, client_id: str = ""):
        data = json.dumps({
            "type": "canvas_updated",
            "canvas_id": canvas_id,
            "updated_at": updated_at,
            "client_id": client_id or "",
        })
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(data)
            except Exception as exc:
                print(f"Broadcast canvas error: {exc}")
                self.active_connections.remove(connection)

    async def broadcast_asset_library_updated(self, updated_at: int = 0):
        data = json.dumps({
            "type": "asset_library_updated",
            "updated_at": updated_at or int(time.time() * 1000),
        })
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(data)
            except Exception as exc:
                print(f"Broadcast asset library error: {exc}")
                self.active_connections.remove(connection)

    async def send_personal_message(self, message: dict, client_id: str):
        ws = self.user_connections.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
            except Exception as exc:
                print(f"Personal message error for {client_id}: {exc}")


def install_quiet_access_log_filter() -> None:
    logging.getLogger("uvicorn.access").addFilter(QuietAccessLogFilter())

