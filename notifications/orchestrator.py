from __future__ import annotations
import logging
from typing import Optional
from datetime import datetime
from decimal import Decimal
import asyncio

from notifications.telegram.client import TelegramClient
from notifications.telegram.manager import NotificationManager, AlertType

logger = logging.getLogger(__name__)


class NotificationOrchestrator:
    def __init__(
        self,
        app_context,
        bot_token: str,
        default_chat_id: str,
    ):
        self.app_context = app_context
        self.risk_manager = app_context.risk_manager
        self.exchange = app_context.exchange_manager

        self.telegram_client = TelegramClient(bot_token, default_chat_id)
        self.notification_manager = NotificationManager(self.telegram_client)
        self.is_initialized = False

    async def initialize(self) -> bool:
        try:
            success = await self.telegram_client.initialize()
            self.is_initialized = success
            if success:
                logger.info("Notification orchestrator initialized")
            else:
                logger.error("Failed to initialize Telegram client")
            return success
        except Exception as e:
            logger.error("Error initializing orchestrator: %s", str(e)[:100])
            return False

    async def shutdown(self) -> None:
        try:
            await self.telegram_client.flush_queue()
            await self.telegram_client.shutdown()
            self.is_initialized = False
            logger.info("Notification orchestrator shut down")
        except Exception as e:
            logger.error("Error shutting down orchestrator: %s", str(e)[:100])

    async def notify_order_executed(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }

        return await self.notification_manager.trigger_alert(AlertType.ORDER_EXECUTED, data)

    async def notify_position_closed(
        self,
        symbol: str,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: Decimal,
        pnl: Decimal,
        pnl_pct: Decimal,
        exit_reason: str,
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
        }

        return await self.notification_manager.trigger_alert(AlertType.POSITION_CLOSED, data)

    async def notify_risk_breach(
        self,
        alert_type: str,
        message: str,
        metric_value: Optional[Decimal] = None,
        threshold: Optional[Decimal] = None,
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "alert_type": alert_type,
            "message": message,
            "metric_value": metric_value,
            "threshold": threshold,
        }

        return await self.notification_manager.trigger_alert(AlertType.RISK_BREACH, data)

    async def notify_daily_loss_warning(
        self,
        daily_loss_pct: Decimal,
        threshold_pct: Decimal,
        message: str = "Daily loss approaching limit",
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "daily_loss_pct": daily_loss_pct,
            "threshold_pct": threshold_pct,
            "message": message,
        }

        return await self.notification_manager.trigger_alert(AlertType.DAILY_LOSS_WARNING, data)

    async def notify_drawdown_warning(
        self,
        drawdown_pct: Decimal,
        threshold_pct: Decimal,
        message: str = "Drawdown approaching limit",
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "drawdown_pct": drawdown_pct,
            "threshold_pct": threshold_pct,
            "message": message,
        }

        return await self.notification_manager.trigger_alert(AlertType.DRAWDOWN_WARNING, data)

    async def notify_max_positions_reached(
        self,
        open_positions: int,
        max_positions: int,
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "open_positions": open_positions,
            "max_positions": max_positions,
            "message": f"Maximum positions reached: {open_positions}/{max_positions}",
        }

        return await self.notification_manager.trigger_alert(AlertType.MAX_POSITIONS_REACHED, data)

    async def notify_daily_summary(
        self,
        equity: Decimal,
        daily_pnl: Decimal,
        daily_pnl_pct: Decimal,
        trades_count: int,
        win_rate: Decimal,
        drawdown: Decimal,
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "equity": equity,
            "daily_pnl": daily_pnl,
            "daily_pnl_pct": daily_pnl_pct,
            "trades_count": trades_count,
            "win_rate": win_rate,
            "drawdown": drawdown,
        }

        return await self.notification_manager.trigger_alert(AlertType.DAILY_SUMMARY, data)

    async def notify_status_update(
        self,
        status: str,
        open_positions: int,
        total_risk_pct: Decimal,
        is_within_limits: bool,
    ) -> bool:
        if not self.is_initialized:
            return False

        data = {
            "status": status,
            "open_positions": open_positions,
            "total_risk_pct": total_risk_pct,
            "is_within_limits": is_within_limits,
        }

        return await self.notification_manager.trigger_alert(AlertType.STATUS_UPDATE, data)

    def get_queue_status(self) -> dict:
        return {
            "queue_size": self.telegram_client.queue_size(),
            "is_connected": self.telegram_client.is_connected,
            "is_initialized": self.is_initialized,
        }

    async def flush_pending_messages(self) -> int:
        if not self.is_initialized:
            return 0

        return await self.telegram_client.flush_queue()

    def get_alert_configuration(self) -> dict:
        return self.notification_manager.get_alert_status()

    def configure_alert(
        self,
        alert_type: str,
        enabled: bool = None,
        throttle_seconds: int = None,
    ) -> bool:
        try:
            alert_enum = AlertType[alert_type.upper()]

            if enabled is not None:
                if enabled:
                    self.notification_manager.enable_alert(alert_enum)
                else:
                    self.notification_manager.disable_alert(alert_enum)

            if throttle_seconds is not None:
                self.notification_manager.set_throttle(alert_enum, throttle_seconds)

            logger.info("Alert configured: %s", alert_type)
            return True
        except Exception as e:
            logger.error("Error configuring alert: %s", str(e)[:100])
            return False
