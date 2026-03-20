from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, List, Callable
import uuid

from exchange.types import OrderRequest, OrderResponse
from risk.calculator import RiskCalculator, RiskMetrics, PositionRisk
from risk.guards import RiskGuardianSystem, GuardStatus, GuardResult
from risk.sizing import AdaptivePositionSizer, SizingMethod, SizingResult
from risk.engine import RiskMonitoringEngine, RiskAlert

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(
        self,
        uow,
        initial_account_equity: Decimal,
        per_trade_loss_pct: Decimal = Decimal("2"),
        daily_loss_limit_pct: Decimal = Decimal("5"),
        max_open_positions: int = 10,
        portfolio_risk_limit_pct: Decimal = Decimal("10"),
        kelly_fraction: Decimal = Decimal("0.25"),
    ):
        self.uow = uow
        self.initial_account_equity = initial_account_equity
        
        self.calculator = RiskCalculator(
            account_equity=initial_account_equity,
            max_risk_per_trade_pct=per_trade_loss_pct,
            max_drawdown_pct=daily_loss_limit_pct,
            max_open_positions=max_open_positions,
            kelly_fraction=kelly_fraction,
        )
        
        self.guardian = RiskGuardianSystem(
            per_trade_loss_pct=per_trade_loss_pct,
            daily_loss_limit_pct=daily_loss_limit_pct,
            max_positions=max_open_positions,
            portfolio_risk_limit_pct=portfolio_risk_limit_pct,
        )
        
        self.sizer = AdaptivePositionSizer(
            default_method=SizingMethod.FIXED_PERCENTAGE,
        )
        
        self.monitor = RiskMonitoringEngine(
            uow=uow,
            risk_calculator=self.calculator,
            risk_guardian=self.guardian,
            monitoring_interval=5.0,
        )
        
        self._active_orders: dict[str, OrderRequest] = {}

    async def validate_order_pre_placement(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        quantity: Decimal,
    ) -> tuple[bool, str, List[GuardResult]]:
        is_valid, message, results = self.guardian.validate_order_pre_execution(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            quantity=quantity,
            account_equity=self.calculator.account_equity,
        )

        if not is_valid:
            logger.warning(
                "Order validation failed: %s | Symbol: %s",
                message,
                symbol,
            )

        return is_valid, message, results

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Optional[Decimal] = None,
        method: SizingMethod = SizingMethod.FIXED_PERCENTAGE,
        win_rate_pct: Decimal = Decimal("55"),
        atr: Optional[Decimal] = None,
    ) -> SizingResult:
        kwargs = {
            "take_profit_price": take_profit_price or entry_price,
            "win_rate_pct": win_rate_pct,
            "avg_win_loss_ratio": Decimal("1.5"),
        }
        
        if atr:
            kwargs["atr"] = atr

        result = self.sizer.calculate(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            account_equity=self.calculator.account_equity,
            method=method,
            **kwargs,
        )

        logger.info(
            "Position size calculated | Symbol: %s | Qty: %.4f | Method: %s | Reason: %s",
            symbol,
            result.quantity,
            result.method.value,
            result.reasoning,
        )

        return result

    async def register_executed_order(
        self,
        order: OrderResponse,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
    ) -> bool:
        try:
            is_valid, message, _ = await self.validate_order_pre_placement(
                symbol=order.symbol,
                entry_price=order.price or Decimal("0"),
                stop_loss_price=stop_loss_price,
                quantity=order.quantity,
            )

            if not is_valid:
                logger.error("Order post-execution validation failed: %s", message)
                return False

            self.calculator.register_position(
                symbol=order.symbol,
                quantity=order.quantity,
                entry_price=order.price or Decimal("0"),
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
            )

            self.guardian.register_executed_order(
                symbol=order.symbol,
                entry_price=order.price or Decimal("0"),
                stop_loss_price=stop_loss_price,
                quantity=order.quantity,
            )

            self._active_orders[order.order_id] = OrderRequest(
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                stop_price=stop_loss_price,
            )

            logger.info(
                "Order registered in risk system | Order ID: %s | Symbol: %s",
                order.order_id,
                order.symbol,
            )
            return True

        except Exception as e:
            logger.error("Error registering executed order: %s", str(e)[:100])
            return False

    async def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        quantity: Decimal,
        exit_reason: str = "TAKE_PROFIT",
    ) -> Optional[RiskAlert]:
        if symbol not in self.calculator.positions:
            logger.warning("Position not found for closure: %s", symbol)
            return None

        position = self.calculator.positions[symbol]
        
        if exit_reason == "TAKE_PROFIT":
            realized_pnl = (exit_price - position.entry_price) * quantity
        elif exit_reason == "STOP_LOSS":
            realized_pnl = -position.max_loss_amount
        else:
            realized_pnl = (exit_price - position.entry_price) * quantity

        self.calculator.close_position(
            symbol=symbol,
            exit_price=exit_price,
            realized_pnl=realized_pnl,
        )

        close_result = self.guardian.close_executed_order(
            symbol=symbol,
            realized_pnl=realized_pnl,
        )

        if close_result.status == GuardStatus.BLOCKED:
            logger.warning("Loss alert on position close: %s", close_result.message)
            return RiskAlert(
                alert_id=f"close_{symbol}_{int(datetime.utcnow().timestamp() * 1000)}",
                timestamp=datetime.utcnow(),
                alert_type="POSITION_CLOSE_WITH_LOSS",
                severity="WARNING" if realized_pnl < 0 else "INFO",
                symbol=symbol,
                message=f"Position {symbol} closed | P&L: {realized_pnl:.2f} | Reason: {exit_reason}",
                metric_value=realized_pnl,
                threshold=Decimal("0"),
                action_taken="POSITION_CLOSED",
                metadata={
                    "exit_price": float(exit_price),
                    "entry_price": float(position.entry_price),
                    "quantity": float(quantity),
                    "exit_reason": exit_reason,
                },
            )

        for order_id, order in list(self._active_orders.items()):
            if order.symbol == symbol:
                del self._active_orders[order_id]

        logger.info(
            "Position closed | Symbol: %s | P&L: %.2f | Reason: %s",
            symbol,
            realized_pnl,
            exit_reason,
        )
        return None

    def get_risk_metrics(self) -> RiskMetrics:
        return self.calculator.get_risk_metrics()

    def get_guardian_status(self) -> dict:
        return self.guardian.get_guardian_status(self.calculator.account_equity)

    async def start_monitoring(self) -> None:
        await self.monitor.start()
        logger.info("Risk monitoring started")

    async def stop_monitoring(self) -> None:
        await self.monitor.stop()
        logger.info("Risk monitoring stopped")

    def subscribe_to_risk_alerts(
        self,
        callback: Callable[[RiskAlert], None],
    ) -> None:
        self.monitor.subscribe_to_alerts(callback)

    def unsubscribe_from_risk_alerts(
        self,
        callback: Callable[[RiskAlert], None],
    ) -> None:
        self.monitor.unsubscribe_from_alerts(callback)

    def get_active_positions(self) -> dict[str, PositionRisk]:
        return self.calculator.positions.copy()

    def get_active_orders_count(self) -> int:
        return len(self._active_orders)

    def is_trading_allowed(self, metrics=None) -> bool:
        if self.guardian.drawdown_guard.is_triggered:
            return False
        if metrics is None:
            metrics = self.calculator.get_risk_metrics()
        return metrics.is_within_limits

    async def reset_daily_limits(self) -> None:
        self.guardian.reset_daily_limits(self.calculator.account_equity)
        self.calculator.reset_daily_loss()
        logger.info("Daily limits reset by risk manager")

    def update_account_equity(self, new_equity: Decimal) -> None:
        self.calculator.account_equity = new_equity
        self.calculator.peak_equity = max(self.calculator.peak_equity, new_equity)
        logger.debug("Account equity updated to: %.2f", new_equity)

    def get_summary(self) -> dict:
        try:
            metrics = self.calculator.get_risk_metrics()
        except Exception:
            metrics = None

        def _f(val, default=0.0):
            try:
                return float(val) if val is not None else default
            except Exception:
                return default

        equity = _f(getattr(metrics, "account_equity", None))
        initial = _f(self.initial_account_equity) if self.initial_account_equity is not None else 0.0
        total_pnl = equity - initial
        total_pnl_pct = (total_pnl / initial * 100.0) if initial != 0 else 0.0

        try:
            guardian_status = self.get_guardian_status()
        except Exception:
            guardian_status = {}

        try:
            is_trading_allowed = self.is_trading_allowed(metrics)
        except Exception:
            is_trading_allowed = False

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "account_equity": equity,
            "initial_equity": initial,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "open_positions": _f(getattr(metrics, "open_positions_count", None)),
            "max_open_positions": _f(getattr(self.calculator, "max_open_positions", None)),
            "total_risk_exposure": _f(getattr(metrics, "total_risk_exposure", None)),
            "total_risk_pct": _f(getattr(metrics, "total_risk_pct", None)),
            "daily_loss": _f(getattr(metrics, "daily_loss_realized", None)),
            "daily_loss_pct": _f(getattr(metrics, "daily_loss_pct", None)),
            "drawdown_pct": _f(getattr(metrics, "drawdown_pct", None)),
            "max_drawdown_pct": _f(getattr(self.calculator, "max_drawdown_pct", None)),
            "is_within_limits": getattr(metrics, "is_within_limits", True) if metrics else True,
            "is_trading_allowed": is_trading_allowed,
            "breached_limits": getattr(metrics, "breached_limits", []) if metrics else [],
            "guardian_status": guardian_status,
        }
