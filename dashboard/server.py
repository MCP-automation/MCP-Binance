from __future__ import annotations
import logging
from fastapi import FastAPI, WebSocket, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import json
from datetime import datetime
from typing import Optional
import asyncio

logger = logging.getLogger(__name__)


class DashboardServer:
    def __init__(self, app_context):
        self.app_context = app_context
        self.exchange = app_context.exchange_manager
        self.risk_manager = app_context.risk_manager
        self.backtest_runner = app_context.backtest_runner
        self.active_connections: list[WebSocket] = []

    async def broadcast_update(self, message: dict) -> None:
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.active_connections.remove(connection)

    async def get_dashboard_data(self) -> dict:
        try:
            metrics = self.risk_manager.get_risk_metrics()
            summary = self.risk_manager.get_summary()

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "account": {
                    "equity": float(metrics.account_equity),
                    "initial_equity": float(summary.get("initial_equity", 0)),
                    "total_pnl": float(summary.get("total_pnl", 0)),
                    "total_pnl_pct": float(summary.get("total_pnl_pct", 0)),
                },
                "risk": {
                    "total_exposure": float(metrics.total_risk_exposure),
                    "exposure_pct": float(metrics.total_risk_pct),
                    "drawdown_pct": float(metrics.drawdown_pct),
                    "daily_loss": float(metrics.daily_loss_realized),
                    "daily_loss_pct": float(metrics.daily_loss_pct),
                },
                "positions": {
                    "open_count": metrics.open_positions_count,
                    "max_allowed": summary.get("max_open_positions", 10),
                    "is_within_limits": metrics.is_within_limits,
                },
                "summary": summary,
            }
        except Exception as e:
            logger.error("Error getting dashboard data: %s", str(e)[:100])
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)[:200],
            }


def create_app(app_context) -> FastAPI:
    dashboard_server = DashboardServer(app_context)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Dashboard server started")
        yield
        logger.info("Dashboard server stopped")

    app = FastAPI(title="Binance Trading Dashboard", lifespan=lifespan)

    @app.get("/api/health")
    async def health_check() -> dict:
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/api/dashboard")
    async def get_dashboard() -> dict:
        data = await dashboard_server.get_dashboard_data()
        return data

    @app.get("/api/positions")
    async def get_positions() -> dict:
        try:
            positions = dashboard_server.risk_manager.get_active_positions()
            return {
                "success": True,
                "positions": [
                    {
                        "symbol": pos.symbol,
                        "quantity": float(pos.entry_quantity),
                        "entry_price": float(pos.entry_price),
                        "stop_loss": float(pos.stop_loss) if pos.stop_loss else None,
                        "take_profit": float(pos.take_profit) if pos.take_profit else None,
                        "max_loss_pct": float(pos.max_loss_pct),
                        "risk_reward": float(pos.risk_reward_ratio),
                        "created_at": pos.created_at.isoformat(),
                    }
                    for pos in positions.values()
                ],
            }
        except Exception as e:
            logger.error("Error getting positions: %s", str(e)[:100])
            return {"success": False, "error": str(e)[:200]}

    @app.get("/api/metrics")
    async def get_metrics() -> dict:
        try:
            metrics = dashboard_server.risk_manager.get_risk_metrics()
            return {
                "success": True,
                "metrics": {
                    "account_equity": float(metrics.account_equity),
                    "total_risk_exposure": float(metrics.total_risk_exposure),
                    "total_risk_pct": float(metrics.total_risk_pct),
                    "open_positions": metrics.open_positions_count,
                    "max_position_risk": float(metrics.max_position_risk),
                    "daily_loss": float(metrics.daily_loss_realized),
                    "daily_loss_pct": float(metrics.daily_loss_pct),
                    "drawdown_pct": float(metrics.drawdown_pct),
                    "is_within_limits": metrics.is_within_limits,
                    "breached_limits": metrics.breached_limits,
                },
            }
        except Exception as e:
            logger.error("Error getting metrics: %s", str(e)[:100])
            return {"success": False, "error": str(e)[:200]}

    @app.websocket("/ws/updates")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        dashboard_server.active_connections.append(websocket)
        logger.info("WebSocket client connected | Total: %d", len(dashboard_server.active_connections))

        try:
            initial_data = await dashboard_server.get_dashboard_data()
            await websocket.send_json({"type": "initial", "data": initial_data})

            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
                elif data == "refresh":
                    dashboard_data = await dashboard_server.get_dashboard_data()
                    await websocket.send_json({"type": "update", "data": dashboard_data})

        except Exception as e:
            logger.error("WebSocket error: %s", str(e)[:100])
        finally:
            if websocket in dashboard_server.active_connections:
                dashboard_server.active_connections.remove(websocket)
            logger.info("WebSocket client disconnected | Total: %d", len(dashboard_server.active_connections))

    @app.get("/")
    async def root():
        return FileResponse("dashboard/public/index.html")

    return app
