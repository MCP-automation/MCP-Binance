from __future__ import annotations
import asyncio
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, Callable, List
from dataclasses import dataclass
import json

from risk.calculator import RiskCalculator, RiskMetrics
from risk.guards import RiskGuardianSystem, GuardStatus

logger = logging.getLogger(__name__)


@dataclass
class RiskAlert:
    alert_id: str
    timestamp: datetime
    alert_type: str
    severity: str
    symbol: Optional[str]
    message: str
    metric_value: Optional[Decimal]
    threshold: Optional[Decimal]
    action_taken: str
    metadata: dict


class RiskMonitoringEngine:
    def __init__(
        self,
        uow,
        risk_calculator: RiskCalculator,
        risk_guardian: RiskGuardianSystem,
        monitoring_interval: float = 5.0,
    ):
        self.uow = uow
        self.risk_calculator = risk_calculator
        self.risk_guardian = risk_guardian
        self.monitoring_interval = monitoring_interval
        
        self.is_running = False
        self.monitoring_task: Optional[asyncio.Task] = None
        self.alert_subscribers: List[Callable[[RiskAlert], None]] = []
        self.last_metrics: Optional[RiskMetrics] = None

    def subscribe_to_alerts(self, callback: Callable[[RiskAlert], None]) -> None:
        self.alert_subscribers.append(callback)
        logger.debug("Alert subscriber registered")

    def unsubscribe_from_alerts(self, callback: Callable[[RiskAlert], None]) -> None:
        self.alert_subscribers.discard(callback)
        logger.debug("Alert subscriber unregistered")

    async def _emit_alert(self, alert: RiskAlert) -> None:
        for callback in self.alert_subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                logger.error("Alert callback error: %s", str(e)[:100])

    async def _persist_alert(self, alert: RiskAlert) -> None:
        try:
            async with self.uow as uow:
                await uow.risk_events.create({
                    "id": alert.alert_id,
                    "timestamp": alert.timestamp.isoformat(),
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "symbol": alert.symbol,
                    "message": alert.message,
                    "metric_value": float(alert.metric_value) if alert.metric_value else None,
                    "threshold": float(alert.threshold) if alert.threshold else None,
                    "action_taken": alert.action_taken,
                    "metadata": json.dumps(alert.metadata),
                })
                await uow.commit()
        except Exception as e:
            logger.error("Failed to persist risk alert: %s", str(e)[:100])

    async def check_drawdown_limit(
        self,
        current_equity: Decimal,
    ) -> Optional[RiskAlert]:
        metrics = self.risk_calculator.get_risk_metrics()
        
        if metrics.drawdown_pct > self.risk_calculator.max_drawdown_pct:
            alert = RiskAlert(
                alert_id=f"dd_{int(datetime.utcnow().timestamp() * 1000)}",
                timestamp=datetime.utcnow(),
                alert_type="DRAWDOWN_LIMIT_BREACHED",
                severity="CRITICAL",
                symbol=None,
                message=f"Daily drawdown {metrics.drawdown_pct:.2f}% exceeds limit {self.risk_calculator.max_drawdown_pct}%",
                metric_value=metrics.drawdown_pct,
                threshold=self.risk_calculator.max_drawdown_pct,
                action_taken="TRADING_HALTED",
                metadata={
                    "peak_equity": float(self.risk_calculator.peak_equity),
                    "current_equity": float(current_equity),
                    "drawdown_amount": float(metrics.drawdown_amount),
                },
            )
            await self._emit_alert(alert)
            await self._persist_alert(alert)
            return alert

        return None

    async def check_position_limits(self) -> Optional[RiskAlert]:
        if len(self.risk_calculator.positions) >= self.risk_calculator.max_open_positions:
            alert = RiskAlert(
                alert_id=f"pos_{int(datetime.utcnow().timestamp() * 1000)}",
                timestamp=datetime.utcnow(),
                alert_type="MAX_POSITIONS_REACHED",
                severity="WARNING",
                symbol=None,
                message=f"Maximum open positions ({self.risk_calculator.max_open_positions}) reached",
                metric_value=Decimal(len(self.risk_calculator.positions)),
                threshold=Decimal(self.risk_calculator.max_open_positions),
                action_taken="NEW_ORDERS_BLOCKED",
                metadata={
                    "open_positions": len(self.risk_calculator.positions),
                    "max_allowed": self.risk_calculator.max_open_positions,
                    "symbols": list(self.risk_calculator.positions.keys()),
                },
            )
            await self._emit_alert(alert)
            await self._persist_alert(alert)
            return alert

        return None

    async def check_concentration_limits(self) -> Optional[RiskAlert]:
        metrics = self.risk_calculator.get_risk_metrics()
        max_concentration = self.risk_calculator.max_risk_per_trade_pct * Decimal("3")

        if metrics.total_risk_pct > max_concentration:
            alert = RiskAlert(
                alert_id=f"conc_{int(datetime.utcnow().timestamp() * 1000)}",
                timestamp=datetime.utcnow(),
                alert_type="PORTFOLIO_CONCENTRATION_ALERT",
                severity="WARNING",
                symbol=None,
                message=f"Portfolio risk concentration {metrics.total_risk_pct:.2f}% exceeds threshold {max_concentration}%",
                metric_value=metrics.total_risk_pct,
                threshold=max_concentration,
                action_taken="MANUAL_REVIEW_REQUIRED",
                metadata={
                    "total_risk_exposure": float(metrics.total_risk_exposure),
                    "account_equity": float(metrics.account_equity),
                    "position_count": metrics.open_positions_count,
                },
            )
            await self._emit_alert(alert)
            await self._persist_alert(alert)
            return alert

        return None

    async def check_daily_loss_warning(self) -> Optional[RiskAlert]:
        metrics = self.risk_calculator.get_risk_metrics()
        warning_threshold = self.risk_calculator.max_drawdown_pct * Decimal("0.75")

        if metrics.daily_loss_pct > warning_threshold:
            alert = RiskAlert(
                alert_id=f"dlw_{int(datetime.utcnow().timestamp() * 1000)}",
                timestamp=datetime.utcnow(),
                alert_type="DAILY_LOSS_WARNING",
                severity="WARNING",
                symbol=None,
                message=f"Daily loss {metrics.daily_loss_pct:.2f}% approaching kill-switch threshold {self.risk_calculator.max_drawdown_pct}%",
                metric_value=metrics.daily_loss_pct,
                threshold=warning_threshold,
                action_taken="ALERT_ONLY",
                metadata={
                    "daily_loss_amount": float(metrics.daily_loss_realized),
                    "account_equity": float(metrics.account_equity),
                    "threshold_pct": float(warning_threshold),
                },
            )
            await self._emit_alert(alert)
            await self._persist_alert(alert)
            return alert

        return None

    async def check_position_specific_risk(
        self,
        symbol: str,
        current_price: Decimal,
    ) -> Optional[RiskAlert]:
        if symbol not in self.risk_calculator.positions:
            return None

        position = self.risk_calculator.positions[symbol]
        unrealized_loss = abs(position.entry_price - current_price) * position.quantity

        loss_pct = (unrealized_loss / (position.entry_price * position.quantity)) * Decimal("100")

        if loss_pct > (position.max_loss_pct * Decimal("0.75")):
            alert = RiskAlert(
                alert_id=f"pos_{symbol}_{int(datetime.utcnow().timestamp() * 1000)}",
                timestamp=datetime.utcnow(),
                alert_type="POSITION_LOSS_WARNING",
                severity="WARNING",
                symbol=symbol,
                message=f"Position {symbol} loss approaching stop: {loss_pct:.2f}% of {position.max_loss_pct:.2f}%",
                metric_value=loss_pct,
                threshold=position.max_loss_pct,
                action_taken="MONITORING",
                metadata={
                    "entry_price": float(position.entry_price),
                    "current_price": float(current_price),
                    "quantity": float(position.quantity),
                    "unrealized_loss": float(unrealized_loss),
                    "stop_loss_price": float(position.stop_loss_price),
                },
            )
            await self._emit_alert(alert)
            await self._persist_alert(alert)
            return alert

        return None

    async def _monitoring_loop(self) -> None:
        while self.is_running:
            try:
                metrics = self.risk_calculator.get_risk_metrics()
                self.last_metrics = metrics

                if not metrics.is_within_limits:
                    logger.warning("Risk limits breached: %s", metrics.breached_limits)
                    
                    if "max_drawdown" in metrics.breached_limits:
                        await self.check_drawdown_limit(metrics.account_equity)
                    
                    if "max_positions" in metrics.breached_limits:
                        await self.check_position_limits()
                    
                    if "portfolio_concentration" in metrics.breached_limits:
                        await self.check_concentration_limits()

                await self.check_daily_loss_warning()

                await asyncio.sleep(self.monitoring_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in monitoring loop: %s", str(e)[:100])
                await asyncio.sleep(self.monitoring_interval)

    async def start(self) -> None:
        if self.is_running:
            return

        self.is_running = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Risk monitoring engine started")

    async def stop(self) -> None:
        if not self.is_running:
            return

        self.is_running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Risk monitoring engine stopped")

    def get_current_metrics(self) -> Optional[RiskMetrics]:
        return self.last_metrics

    async def force_check_all_limits(self, current_equity: Decimal) -> List[RiskAlert]:
        alerts = []

        dd_alert = await self.check_drawdown_limit(current_equity)
        if dd_alert:
            alerts.append(dd_alert)

        pos_alert = await self.check_position_limits()
        if pos_alert:
            alerts.append(pos_alert)

        conc_alert = await self.check_concentration_limits()
        if conc_alert:
            alerts.append(conc_alert)

        loss_alert = await self.check_daily_loss_warning()
        if loss_alert:
            alerts.append(loss_alert)

        return alerts
