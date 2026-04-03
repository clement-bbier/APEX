"""FastAPI dashboard for APEX Trading System real-time monitoring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("s10_monitor.dashboard")

_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>APEX Trading Dashboard</title>
    <style>
        body { font-family: monospace; background: #0a0a0a; color: #00ff41; padding: 20px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { border: 1px solid #00ff41; padding: 15px; border-radius: 4px; }
        h1 { color: #00ff41; } h2 { color: #00cc33; font-size: 14px; }
        pre { font-size: 12px; overflow: auto; max-height: 300px; }
        .status-ok { color: #00ff41; } .status-err { color: #ff4141; }
    </style>
</head>
<body>
    <h1>⚡ APEX Trading System</h1>
    <div class="grid">
        <div class="card"><h2>Equity Curve</h2><pre id="equity">Loading...</pre></div>
        <div class="card"><h2>Open Positions</h2><pre id="positions">Loading...</pre></div>
        <div class="card"><h2>Service Health</h2><pre id="health">Loading...</pre></div>
        <div class="card"><h2>Regime</h2><pre id="regime">Loading...</pre></div>
        <div class="card"><h2>Signal Feed</h2><pre id="signals">Loading...</pre></div>
        <div class="card"><h2>Session Context</h2><pre id="session">Loading...</pre></div>
    </div>
    <script>
        const ws = new WebSocket("ws://" + location.host + "/ws");
        ws.onmessage = (e) => {
            const d = JSON.parse(e.data);
            for (const [k, v] of Object.entries(d)) {
                const el = document.getElementById(k);
                if (el) el.textContent = JSON.stringify(v, null, 2);
            }
        };
        ws.onclose = () => { document.body.style.opacity = "0.5"; };
    </script>
</body>
</html>
"""


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            ws: Incoming WebSocket connection.
        """
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection.

        Args:
            ws: WebSocket to remove.
        """
        self._connections.remove(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send data to all connected WebSocket clients.

        Args:
            data: Payload to broadcast.
        """
        payload = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)


class DashboardServer:
    """FastAPI WebSocket dashboard server."""

    def __init__(self, state: StateStore, host: str = "0.0.0.0", port: int = 8080) -> None:  # noqa: S104
        """Initialize dashboard server.

        Args:
            state: Active StateStore for Redis reads.
            host: Bind host.
            port: Bind port.
        """
        self._state = state
        self._host = host
        self._port = port
        self._manager = ConnectionManager()
        self.app = FastAPI(title="APEX Trading Dashboard")
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Register all FastAPI routes and WebSocket endpoint."""
        app = self.app

        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(_DASHBOARD_HTML)

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {"status": "ok"}

        @app.get("/positions")
        async def positions() -> dict[str, Any]:
            try:
                keys_raw = await self._state._ensure_connected().keys("positions:*")
                result = {}
                for k in keys_raw:
                    symbol = k.replace("positions:", "")
                    result[symbol] = await self._state.get(k)
                return result
            except Exception as exc:
                return {"error": str(exc)}

        @app.get("/regime")
        async def regime() -> dict[str, Any]:
            return await self._state.get("regime:current") or {}

        @app.get("/equity")
        async def equity() -> dict[str, Any]:
            curve = await self._state.lrange("equity_curve", 0, 99)
            return {"curve": curve}

        @app.get("/signals")
        async def signals() -> dict[str, Any]:
            try:
                keys_raw = await self._state._ensure_connected().keys("signal:*")
                result = {}
                for k in keys_raw:
                    symbol = k.replace("signal:", "")
                    result[symbol] = await self._state.get(k)
                return result
            except Exception as exc:
                return {"error": str(exc)}

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket) -> None:
            await self._manager.connect(ws)
            try:
                while True:
                    data = await self._build_broadcast()
                    await self._manager.broadcast(data)
                    await asyncio.sleep(2)
            except WebSocketDisconnect:
                self._manager.disconnect(ws)
            except Exception as exc:
                logger.error("WebSocket error", error=str(exc))
                self._manager.disconnect(ws)

    async def _build_broadcast(self) -> dict[str, Any]:
        """Build the broadcast payload from Redis."""
        payload: dict[str, Any] = {}
        try:
            regime = await self._state.get("regime:current")
            payload["regime"] = regime or {}
            curve = await self._state.lrange("equity_curve", 0, 9)
            payload["equity"] = curve
            signals_raw = {}
            try:
                keys = await self._state._ensure_connected().keys("signal:*")
                for k in keys[:5]:
                    sym = k.replace("signal:", "")
                    signals_raw[sym] = await self._state.get(k)
            except Exception as exc:
                logger.debug("signal_fetch_failed", error=str(exc))
            payload["signals"] = signals_raw
            session = (regime or {}).get("session", {})
            payload["session"] = session
        except Exception as exc:
            payload["error"] = str(exc)
        return payload

    async def start(self) -> None:
        """Start the uvicorn server in background."""
        config = uvicorn.Config(
            self.app,
            host=self._host,
            port=self._port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()
