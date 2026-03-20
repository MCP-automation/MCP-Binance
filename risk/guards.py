from __future__ import annotations
import logging
from decimal import Decimal
from enum import Enum
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class GuardStatus(Enum):
    OK = "OK"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass
class GuardResult:
    status: GuardStatus
    message: str
    checks: List[dict]


class PerTradeMaxLossGuard:
    def __init__(self, max_loss_pct: Decimal = Decimal("2")):
        self.max_loss_pct = max_loss_pct

    def check(
        self,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        quantity: Decimal,
    ) -> GuardResult:
        checks = []

        if entry_price <= 0:
            checks.append({
                "check": "entry_price_valid",
                "passed": False,
                "reason": "Entry price must be positive",
            })
            return GuardResult(
                status=GuardStatus.BLOCKED,
                message="Entry price invalid",
                checks=checks,
            )

        if stop_loss_price < 0:
            checks.append({
                "check": "stop_loss_price_valid",
                "passed": False,
                "reason": "Stop loss cannot be negative",
            })
            return GuardResult(
                status=GuardStatus.BLOCKED,
                message="Stop loss invalid",
                checks=checks,
            )

        loss_per_unit = abs(entry_price - stop_loss_price)
        loss_pct = (loss_per_unit / entry_price) * Decimal("100")

        loss_check_passed = loss_pct <= self.max_loss_pct
        checks.append({
            "check": "loss_percentage",
            "passed": loss_check_passed,
            "actual": float(loss_pct),
            "max": float(self.max_loss_pct),
        })

        status = GuardStatus.OK if loss_check_passed else GuardStatus.BLOCKED
        message = f"Loss {loss_pct:.2f}% {'OK' if loss_check_passed else 'EXCEEDS ' + str(self.max_loss_pct) + '%'}"

        return GuardResult(
            status=status,
            message=message,
            checks=checks,
        )


class DailyDrawdownKillSwitch:
    def __init__(self, daily_loss_limit_pct: Decimal = Decimal("5")):
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.daily_loss = Decimal("0")
        self.daily_start_equity = Decimal("0")
        self.last_reset = datetime.utcnow()
        self.is_triggered = False

    def update_loss(self, loss_amount: Decimal) -> GuardResult:
        checks = []
        
        if loss_amount < 0:
            loss_amount = abs(loss_amount)

        self.daily_loss += loss_amount
        loss_pct = (self.daily_loss / self.daily_start_equity * Decimal("100")) if self.daily_start_equity > 0 else Decimal("0")

        is_breached = loss_pct > self.daily_loss_limit_pct
        
        checks.append({
            "check": "daily_drawdown_limit",
            "passed": not is_breached,
            "current_loss_pct": float(loss_pct),
            "limit_pct": float(self.daily_loss_limit_pct),
        })

        if is_breached and not self.is_triggered:
            self.is_triggered = True
            status = GuardStatus.BLOCKED
            message = f"Daily loss {loss_pct:.2f}% EXCEEDS {self.daily_loss_limit_pct}% - TRADING HALTED"
            logger.critical(message)
        else:
            status = GuardStatus.OK if not self.is_triggered else GuardStatus.BLOCKED
            message = f"Daily loss {loss_pct:.2f}% {'OK' if not self.is_triggered else 'HALTED'}"

        return GuardResult(
            status=status,
            message=message,
            checks=checks,
        )

    def reset_daily(self, start_equity: Decimal) -> None:
        self.daily_loss = Decimal("0")
        self.daily_start_equity = start_equity
        self.last_reset = datetime.utcnow()
        self.is_triggered = False
        logger.info("Daily drawdown kill-switch reset | Start equity: %.2f", start_equity)

    def check_status(self, current_equity: Decimal) -> GuardResult:
        checks = []
        
        if self.is_triggered:
            checks.append({
                "check": "trading_halted",
                "halted": True,
                "reason": "Daily loss limit exceeded",
            })
            return GuardResult(
                status=GuardStatus.BLOCKED,
                message="KILL-SWITCH ACTIVE - All trading halted",
                checks=checks,
            )

        current_loss_pct = ((self.daily_start_equity - current_equity) / self.daily_start_equity * Decimal("100")) if self.daily_start_equity > 0 else Decimal("0")

        warning_threshold = self.daily_loss_limit_pct * Decimal("0.75")
        
        if current_loss_pct > warning_threshold:
            status = GuardStatus.WARNING
            message = f"Daily loss at {current_loss_pct:.2f}% - approaching limit of {self.daily_loss_limit_pct}%"
        else:
            status = GuardStatus.OK
            message = f"Daily loss {current_loss_pct:.2f}% - within limits"

        checks.append({
            "check": "daily_loss_status",
            "current_pct": float(current_loss_pct),
            "limit_pct": float(self.daily_loss_limit_pct),
            "warning_threshold": float(warning_threshold),
        })

        return GuardResult(
            status=status,
            message=message,
            checks=checks,
        )


class MaxOpenPositionsGuard:
    def __init__(self, max_positions: int = 10):
        self.max_positions = max_positions
        self.open_positions = 0

    def check(self) -> GuardResult:
        checks = [
            {
                "check": "max_open_positions",
                "passed": self.open_positions < self.max_positions,
                "current": self.open_positions,
                "max": self.max_positions,
            }
        ]

        if self.open_positions >= self.max_positions:
            return GuardResult(
                status=GuardStatus.BLOCKED,
                message=f"Max positions ({self.max_positions}) reached",
                checks=checks,
            )

        return GuardResult(
            status=GuardStatus.OK,
            message=f"Position slots available: {self.max_positions - self.open_positions}",
            checks=checks,
        )

    def increment(self) -> None:
        self.open_positions += 1

    def decrement(self) -> None:
        self.open_positions = max(0, self.open_positions - 1)

    def reset(self) -> None:
        self.open_positions = 0


class PortfolioConcentrationGuard:
    def __init__(self, max_risk_pct: Decimal = Decimal("10")):
        self.max_risk_pct = max_risk_pct
        self.position_risks: dict[str, Decimal] = {}

    def check(self, new_risk: Decimal, account_equity: Decimal) -> GuardResult:
        checks = []

        total_risk = sum(self.position_risks.values()) + new_risk
        total_risk_pct = (total_risk / account_equity * Decimal("100")) if account_equity > 0 else Decimal("100")

        is_within_limit = total_risk_pct <= self.max_risk_pct
        checks.append({
            "check": "portfolio_concentration",
            "passed": is_within_limit,
            "total_risk_pct": float(total_risk_pct),
            "max_risk_pct": float(self.max_risk_pct),
        })

        status = GuardStatus.OK if is_within_limit else GuardStatus.BLOCKED
        message = f"Portfolio risk {total_risk_pct:.2f}% {'OK' if is_within_limit else 'EXCEEDS ' + str(self.max_risk_pct) + '%'}"

        return GuardResult(
            status=status,
            message=message,
            checks=checks,
        )

    def register_position(self, symbol: str, risk_amount: Decimal) -> None:
        self.position_risks[symbol] = risk_amount

    def unregister_position(self, symbol: str) -> None:
        self.position_risks.pop(symbol, None)

    def get_total_risk(self) -> Decimal:
        return sum(self.position_risks.values())


class RiskGuardianSystem:
    def __init__(
        self,
        per_trade_loss_pct: Decimal = Decimal("2"),
        daily_loss_limit_pct: Decimal = Decimal("5"),
        max_positions: int = 10,
        portfolio_risk_limit_pct: Decimal = Decimal("10"),
    ):
        self.per_trade_guard = PerTradeMaxLossGuard(per_trade_loss_pct)
        self.drawdown_guard = DailyDrawdownKillSwitch(daily_loss_limit_pct)
        self.positions_guard = MaxOpenPositionsGuard(max_positions)
        self.concentration_guard = PortfolioConcentrationGuard(portfolio_risk_limit_pct)

    def validate_order_pre_execution(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        quantity: Decimal,
        account_equity: Decimal,
    ) -> tuple[bool, str, List[GuardResult]]:
        results = []

        if self.drawdown_guard.is_triggered:
            return False, "Daily kill-switch active - trading halted", results

        per_trade_result = self.per_trade_guard.check(
            entry_price,
            stop_loss_price,
            quantity,
        )
        results.append(per_trade_result)
        if per_trade_result.status == GuardStatus.BLOCKED:
            return False, per_trade_result.message, results

        positions_result = self.positions_guard.check()
        results.append(positions_result)
        if positions_result.status == GuardStatus.BLOCKED:
            return False, positions_result.message, results

        risk_amount = abs(entry_price - stop_loss_price) * quantity
        concentration_result = self.concentration_guard.check(risk_amount, account_equity)
        results.append(concentration_result)
        if concentration_result.status == GuardStatus.BLOCKED:
            return False, concentration_result.message, results

        return True, "All guards passed", results

    def register_executed_order(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        quantity: Decimal,
    ) -> None:
        self.positions_guard.increment()
        risk_amount = abs(entry_price - stop_loss_price) * quantity
        self.concentration_guard.register_position(symbol, risk_amount)
        logger.info("Order registered in guardian system: %s", symbol)

    def close_executed_order(
        self,
        symbol: str,
        realized_pnl: Decimal,
    ) -> GuardResult:
        self.positions_guard.decrement()
        self.concentration_guard.unregister_position(symbol)

        if realized_pnl < 0:
            loss_result = self.drawdown_guard.update_loss(abs(realized_pnl))
            logger.warning("Loss recorded: %s | P&L: %.2f", symbol, realized_pnl)
            return loss_result

        return GuardResult(
            status=GuardStatus.OK,
            message=f"Position closed with profit: {realized_pnl:.2f}",
            checks=[],
        )

    def get_guardian_status(self, current_equity: Decimal) -> dict:
        return {
            "per_trade_guard": {
                "max_loss_pct": float(self.per_trade_guard.max_loss_pct),
                "active": True,
            },
            "drawdown_guard": {
                "daily_loss_limit_pct": float(self.drawdown_guard.daily_loss_limit_pct),
                "is_triggered": self.drawdown_guard.is_triggered,
                "current_daily_loss": float(self.drawdown_guard.daily_loss),
            },
            "positions_guard": {
                "max_positions": self.positions_guard.max_positions,
                "current_positions": self.positions_guard.open_positions,
                "available_slots": self.positions_guard.max_positions - self.positions_guard.open_positions,
            },
            "concentration_guard": {
                "max_risk_pct": float(self.concentration_guard.max_risk_pct),
                "current_risk": float(self.concentration_guard.get_total_risk()),
            },
        }

    def reset_daily_limits(self, start_equity: Decimal) -> None:
        self.drawdown_guard.reset_daily(start_equity)
        logger.info("Daily limits reset by guardian system")
