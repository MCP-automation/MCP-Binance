from __future__ import annotations
import logging
from typing import Optional, Callable, Dict, List
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class AlertType(Enum):
    ORDER_EXECUTED = "ORDER_EXECUTED"
    POSITION_CLOSED = "POSITION_CLOSED"
    RISK_BREACH = "RISK_BREACH"
    DAILY_LOSS_WARNING = "DAILY_LOSS_WARNING"
    DRAWDOWN_WARNING = "DRAWDOWN_WARNING"
    MAX_POSITIONS_REACHED = "MAX_POSITIONS_REACHED"
    TAKE_PROFIT_HIT = "TAKE_PROFIT_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    DAILY_SUMMARY = "DAILY_SUMMARY"
    STATUS_UPDATE = "STATUS_UPDATE"


class AlertSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertTrigger:
    def __init__(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        enabled: bool = True,
        throttle_seconds: int = 0,
    ):
        self.alert_type = alert_type
        self.severity = severity
        self.enabled = enabled
        self.throttle_seconds = throttle_seconds
        self.last_triggered_at: Optional[datetime] = None

    def can_trigger(self) -> bool:
        if not self.enabled:
            return False

        if not self.last_triggered_at:
            return True

        elapsed = (datetime.utcnow() - self.last_triggered_at).total_seconds()
        return elapsed >= self.throttle_seconds

    def mark_triggered(self) -> None:
        self.last_triggered_at = datetime.utcnow()


class NotificationManager:
    def __init__(self, telegram_client):
        self.telegram_client = telegram_client
        self.triggers: Dict[AlertType, AlertTrigger] = {}
        self.alert_handlers: Dict[AlertType, Callable] = {}
        self.daily_summary_time = "00:00"
        self.status_check_interval = 3600
        self._initialize_triggers()
        self._initialize_handlers()

    def _initialize_triggers(self) -> None:
        self.triggers[AlertType.ORDER_EXECUTED] = AlertTrigger(
            AlertType.ORDER_EXECUTED,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=0,
        )

        self.triggers[AlertType.POSITION_CLOSED] = AlertTrigger(
            AlertType.POSITION_CLOSED,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=0,
        )

        self.triggers[AlertType.RISK_BREACH] = AlertTrigger(
            AlertType.RISK_BREACH,
            AlertSeverity.CRITICAL,
            enabled=True,
            throttle_seconds=60,
        )

        self.triggers[AlertType.DAILY_LOSS_WARNING] = AlertTrigger(
            AlertType.DAILY_LOSS_WARNING,
            AlertSeverity.WARNING,
            enabled=True,
            throttle_seconds=300,
        )

        self.triggers[AlertType.DRAWDOWN_WARNING] = AlertTrigger(
            AlertType.DRAWDOWN_WARNING,
            AlertSeverity.WARNING,
            enabled=True,
            throttle_seconds=300,
        )

        self.triggers[AlertType.MAX_POSITIONS_REACHED] = AlertTrigger(
            AlertType.MAX_POSITIONS_REACHED,
            AlertSeverity.WARNING,
            enabled=True,
            throttle_seconds=600,
        )

        self.triggers[AlertType.TAKE_PROFIT_HIT] = AlertTrigger(
            AlertType.TAKE_PROFIT_HIT,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=0,
        )

        self.triggers[AlertType.STOP_LOSS_HIT] = AlertTrigger(
            AlertType.STOP_LOSS_HIT,
            AlertSeverity.WARNING,
            enabled=True,
            throttle_seconds=0,
        )

        self.triggers[AlertType.DAILY_SUMMARY] = AlertTrigger(
            AlertType.DAILY_SUMMARY,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=86400,
        )

        self.triggers[AlertType.STATUS_UPDATE] = AlertTrigger(
            AlertType.STATUS_UPDATE,
            AlertSeverity.INFO,
            enabled=True,
            throttle_seconds=3600,
        )

    def _initialize_handlers(self) -> None:
        self.alert_handlers[AlertType.ORDER_EXECUTED] = self._handle_order_executed
        self.alert_handlers[AlertType.POSITION_CLOSED] = self._handle_position_closed
        self.alert_handlers[AlertType.RISK_BREACH] = self._handle_risk_breach
        self.alert_handlers[AlertType.DAILY_LOSS_WARNING] = self._handle_daily_loss_warning
        self.alert_handlers[AlertType.DRAWDOWN_WARNING] = self._handle_drawdown_warning
        self.alert_handlers[AlertType.MAX_POSITIONS_REACHED] = self._handle_max_positions
        self.alert_handlers[AlertType.DAILY_SUMMARY] = self._handle_daily_summary
        self.alert_handlers[AlertType.STATUS_UPDATE] = self._handle_status_update

    async def trigger_alert(
        self,
        alert_type: AlertType,
        data: dict,
    ) -> bool:
        trigger = self.triggers.get(alert_type)
        if not trigger or not trigger.can_trigger():
            return False

        handler = self.alert_handlers.get(alert_type)
        if not handler:
            logger.warning("No handler for alert type: %s", alert_type.value)
            return False

        try:
            success = await handler(data)
            if success:
                trigger.mark_triggered()
            return success
        except Exception as e:
            logger.error("Error triggering alert %s: %s", alert_type.value, str(e)[:100])
            return False

    async def _handle_order_executed(self, data: dict) -> bool:
        return await self.telegram_client.send_order_notification(
            symbol=data.get("symbol", "UNKNOWN"),
            side=data.get("side", "BUY"),
            quantity=data.get("quantity", Decimal("0")),
            price=data.get("price", Decimal("0")),
            stop_loss=data.get("stop_loss"),
            take_profit=data.get("take_profit"),
        )

    async def _handle_position_closed(self, data: dict) -> bool:
        return await self.telegram_client.send_position_closed(
            symbol=data.get("symbol", "UNKNOWN"),
            entry_price=data.get("entry_price", Decimal("0")),
            exit_price=data.get("exit_price", Decimal("0")),
            quantity=data.get("quantity", Decimal("0")),
            pnl=data.get("pnl", Decimal("0")),
            pnl_pct=data.get("pnl_pct", Decimal("0")),
            exit_reason=data.get("exit_reason", "MANUAL"),
        )

    async def _handle_risk_breach(self, data: dict) -> bool:
        return await self.telegram_client.send_risk_alert(
            alert_type=data.get("alert_type", "Unknown"),
            severity="CRITICAL",
            message=data.get("message", "Risk limit breached"),
            metric_value=data.get("metric_value"),
            threshold=data.get("threshold"),
        )

    async def _handle_daily_loss_warning(self, data: dict) -> bool:
        return await self.telegram_client.send_risk_alert(
            alert_type="DAILY_LOSS",
            severity="WARNING",
            message=data.get("message", "Daily loss approaching limit"),
            metric_value=data.get("daily_loss_pct"),
            threshold=data.get("threshold_pct"),
        )

    async def _handle_drawdown_warning(self, data: dict) -> bool:
        return await self.telegram_client.send_risk_alert(
            alert_type="DRAWDOWN",
            severity="WARNING",
            message=data.get("message", "Drawdown approaching limit"),
            metric_value=data.get("drawdown_pct"),
            threshold=data.get("threshold_pct"),
        )

    async def _handle_max_positions(self, data: dict) -> bool:
        return await self.telegram_client.send_risk_alert(
            alert_type="MAX_POSITIONS",
            severity="WARNING",
            message=data.get("message", "Maximum positions reached"),
            metric_value=Decimal(str(data.get("open_positions", 0))),
            threshold=Decimal(str(data.get("max_positions", 10))),
        )

    async def _handle_daily_summary(self, data: dict) -> bool:
        return await self.telegram_client.send_daily_summary(
            equity=data.get("equity", Decimal("0")),
            daily_pnl=data.get("daily_pnl", Decimal("0")),
            daily_pnl_pct=data.get("daily_pnl_pct", Decimal("0")),
            trades_count=data.get("trades_count", 0),
            win_rate=data.get("win_rate", Decimal("0")),
            drawdown=data.get("drawdown", Decimal("0")),
        )

    async def _handle_status_update(self, data: dict) -> bool:
        return await self.telegram_client.send_status_update(
            status=data.get("status", "IDLE"),
            open_positions=data.get("open_positions", 0),
            total_risk_pct=data.get("total_risk_pct", Decimal("0")),
            is_within_limits=data.get("is_within_limits", True),
        )

    def enable_alert(self, alert_type: AlertType) -> None:
        if alert_type in self.triggers:
            self.triggers[alert_type].enabled = True
            logger.info("Alert enabled: %s", alert_type.value)

    def disable_alert(self, alert_type: AlertType) -> None:
        if alert_type in self.triggers:
            self.triggers[alert_type].enabled = False
            logger.info("Alert disabled: %s", alert_type.value)

    def set_throttle(self, alert_type: AlertType, throttle_seconds: int) -> None:
        if alert_type in self.triggers:
            self.triggers[alert_type].throttle_seconds = throttle_seconds
            logger.info("Throttle set for %s: %d seconds", alert_type.value, throttle_seconds)

    def get_alert_status(self) -> dict:
        return {
            alert_type.value: {
                "enabled": trigger.enabled,
                "throttle_seconds": trigger.throttle_seconds,
                "last_triggered": trigger.last_triggered_at.isoformat() if trigger.last_triggered_at else None,
            }
            for alert_type, trigger in self.triggers.items()
        }
