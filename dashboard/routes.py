from __future__ import annotations
import logging
from fastapi import APIRouter, Query
from datetime import datetime, timedelta
from typing import Optional
from decimal import Decimal

logger = logging.getLogger(__name__)


class DashboardRoutes:
    def __init__(self, app_context):
        self.app_context = app_context
        self.exchange = app_context.exchange_manager
        self.risk_manager = app_context.risk_manager
        self.backtest_runner = app_context.backtest_runner
        self.router = APIRouter(prefix="/api", tags=["dashboard"])
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.router.get("/summary")
        async def get_summary() -> dict:
            try:
                summary = self.risk_manager.get_summary()
                return {"success": True, "data": summary}
            except Exception as e:
                logger.error("Error getting summary: %s", str(e)[:100])
                return {"success": False, "error": str(e)[:200]}

        @self.router.get("/equity-history")
        async def get_equity_history(days: Optional[int] = Query(30)) -> dict:
            try:
                equity_curve = self.risk_manager.monitor.get_current_metrics()
                if equity_curve:
                    return {
                        "success": True,
                        "data": {
                            "timestamps": [t.isoformat() for t in equity_curve.timestamps[-days * 24:]],
                            "values": [float(v) for v in equity_curve.equity_values[-days * 24:]],
                            "daily_returns": [float(r) for r in equity_curve.daily_returns[-days:]],
                        },
                    }
                else:
                    return {"success": True, "data": {"timestamps": [], "values": [], "daily_returns": []}}
            except Exception as e:
                logger.error("Error getting equity history: %s", str(e)[:100])
                return {"success": False, "error": str(e)[:200]}

        @self.router.get("/trades")
        async def get_trades(limit: Optional[int] = Query(50)) -> dict:
            try:
                metrics = self.risk_manager.get_risk_metrics()
                trades = self.risk_manager.risk_manager.closed_trades if hasattr(self.risk_manager.risk_manager, 'closed_trades') else []

                return {
                    "success": True,
                    "trades": [
                        {
                            "symbol": t.symbol,
                            "entry_time": t.entry_time.isoformat(),
                            "entry_price": float(t.entry_price),
                            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                            "exit_price": float(t.exit_price) if t.exit_price else None,
                            "quantity": float(t.entry_quantity),
                            "pnl": float(t.net_pnl),
                            "pnl_pct": float(t.realized_pnl_pct) if t.realized_pnl_pct else 0,
                            "duration_minutes": t.duration_minutes,
                            "exit_reason": t.exit_reason,
                        }
                        for t in trades[-limit:]
                    ],
                }
            except Exception as e:
                logger.error("Error getting trades: %s", str(e)[:100])
                return {"success": False, "error": str(e)[:200], "trades": []}

        @self.router.get("/symbols-stats")
        async def get_symbol_stats() -> dict:
            try:
                positions = self.risk_manager.get_active_positions()
                stats = {}

                for symbol, pos in positions.items():
                    stats[symbol] = {
                        "quantity": float(pos.entry_quantity),
                        "entry_price": float(pos.entry_price),
                        "risk_amount": float(pos.max_loss_amount),
                        "risk_pct": float(pos.max_loss_pct),
                        "risk_reward": float(pos.risk_reward_ratio),
                        "duration_minutes": (datetime.utcnow() - pos.created_at).total_seconds() / 60,
                    }

                return {"success": True, "data": stats}
            except Exception as e:
                logger.error("Error getting symbol stats: %s", str(e)[:100])
                return {"success": False, "error": str(e)[:200]}

        @self.router.get("/risk-breakdown")
        async def get_risk_breakdown() -> dict:
            try:
                metrics = self.risk_manager.get_risk_metrics()
                positions = self.risk_manager.get_active_positions()

                breakdown = {}
                total_risk = metrics.total_risk_exposure

                for symbol, pos in positions.items():
                    risk_pct = (pos.max_loss_amount / total_risk * 100) if total_risk > 0 else 0
                    breakdown[symbol] = {
                        "risk_amount": float(pos.max_loss_amount),
                        "risk_pct_of_portfolio": float(risk_pct),
                    }

                return {"success": True, "data": breakdown}
            except Exception as e:
                logger.error("Error getting risk breakdown: %s", str(e)[:100])
                return {"success": False, "error": str(e)[:200]}

        @self.router.get("/daily-stats")
        async def get_daily_stats() -> dict:
            try:
                metrics = self.risk_manager.get_risk_metrics()

                return {
                    "success": True,
                    "data": {
                        "daily_loss": float(metrics.daily_loss_realized),
                        "daily_loss_pct": float(metrics.daily_loss_pct),
                        "daily_loss_limit_pct": float(self.risk_manager.risk_manager.max_drawdown_pct),
                        "daily_loss_remaining_pct": float(
                            self.risk_manager.risk_manager.max_drawdown_pct - metrics.daily_loss_pct
                        ),
                        "open_positions": metrics.open_positions_count,
                    },
                }
            except Exception as e:
                logger.error("Error getting daily stats: %s", str(e)[:100])
                return {"success": False, "error": str(e)[:200]}

    def get_router(self) -> APIRouter:
        return self.router
