from __future__ import annotations
import logging
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

logger = logging.getLogger(__name__)


@dataclass
class PositionRisk:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    stop_loss_price: Decimal
    take_profit_price: Decimal
    max_loss_amount: Decimal
    max_loss_pct: Decimal
    risk_reward_ratio: Decimal
    created_at: datetime


@dataclass
class DrawdownSnapshot:
    timestamp: datetime
    peak_equity: Decimal
    current_equity: Decimal
    drawdown_amount: Decimal
    drawdown_pct: Decimal
    is_breached: bool


@dataclass
class RiskMetrics:
    account_equity: Decimal
    total_risk_exposure: Decimal
    total_risk_pct: Decimal
    open_positions_count: int
    max_position_risk: Decimal
    daily_loss_realized: Decimal
    daily_loss_pct: Decimal
    drawdown_pct: Decimal
    is_within_limits: bool
    breached_limits: List[str]


class RiskCalculator:
    def __init__(
        self,
        account_equity: Decimal,
        max_risk_per_trade_pct: Decimal = Decimal("2"),
        max_drawdown_pct: Decimal = Decimal("20"),
        max_open_positions: int = 10,
        kelly_fraction: Decimal = Decimal("0.25"),
    ):
        self.account_equity = account_equity
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.kelly_fraction = kelly_fraction
        
        self.peak_equity = account_equity
        self.positions: dict[str, PositionRisk] = {}
        self.daily_loss = Decimal("0")
        self.drawdown_history: List[DrawdownSnapshot] = []

    def validate_order_entry(
        self,
        symbol: str,
        quantity: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
    ) -> tuple[bool, str]:
        errors = []

        loss_amount = abs(entry_price - stop_loss_price) * quantity
        loss_pct = (loss_amount / (entry_price * quantity)) * Decimal("100")

        if loss_pct > self.max_risk_per_trade_pct:
            errors.append(
                f"Per-trade loss {loss_pct:.2f}% exceeds max {self.max_risk_per_trade_pct}%"
            )

        if len(self.positions) >= self.max_open_positions:
            errors.append(
                f"Max open positions ({self.max_open_positions}) already reached"
            )

        total_risk = sum(p.max_loss_amount for p in self.positions.values())
        total_risk += loss_amount
        total_risk_pct = (total_risk / self.account_equity) * Decimal("100")

        if total_risk_pct > (self.max_risk_per_trade_pct * Decimal("3")):
            errors.append(
                f"Total portfolio risk {total_risk_pct:.2f}% too concentrated"
            )

        if errors:
            return False, "; ".join(errors)

        return True, "OK"

    def calculate_position_size_kelly(
        self,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        win_rate_pct: Decimal = Decimal("55"),
        avg_win_loss_ratio: Decimal = Decimal("1.5"),
    ) -> Decimal:
        if entry_price <= 0 or stop_loss_price < 0:
            return Decimal("0")

        win_pct = win_rate_pct / Decimal("100")
        loss_pct = (Decimal("100") - win_rate_pct) / Decimal("100")

        kelly_decimal = (
            (win_pct * avg_win_loss_ratio - loss_pct) / avg_win_loss_ratio
        )

        if kelly_decimal <= 0:
            return Decimal("0")

        optimal_fraction = kelly_decimal * self.kelly_fraction
        optimal_fraction = max(Decimal("0"), min(optimal_fraction, Decimal("0.25")))

        risk_amount = self.account_equity * optimal_fraction * self.max_risk_per_trade_pct / Decimal("100")

        loss_per_unit = abs(entry_price - stop_loss_price)
        if loss_per_unit == 0:
            return Decimal("0")

        quantity = risk_amount / loss_per_unit
        return quantity.quantize(Decimal("0.001"))

    def calculate_position_size_fixed_pct(
        self,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        risk_pct: Decimal = Decimal("2"),
    ) -> Decimal:
        if entry_price <= 0 or stop_loss_price < 0:
            return Decimal("0")

        risk_amount = self.account_equity * risk_pct / Decimal("100")
        loss_per_unit = abs(entry_price - stop_loss_price)

        if loss_per_unit == 0:
            return Decimal("0")

        quantity = risk_amount / loss_per_unit
        return quantity.quantize(Decimal("0.001"))

    def register_position(
        self,
        symbol: str,
        quantity: Decimal,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
    ) -> bool:
        is_valid, msg = self.validate_order_entry(
            symbol,
            quantity,
            entry_price,
            stop_loss_price,
            take_profit_price,
        )

        if not is_valid:
            logger.error("Position validation failed: %s", msg)
            return False

        loss_amount = abs(entry_price - stop_loss_price) * quantity
        loss_pct = (loss_amount / (entry_price * quantity)) * Decimal("100")
        
        profit_amount = abs(take_profit_price - entry_price) * quantity
        risk_reward = (profit_amount / loss_amount) if loss_amount > 0 else Decimal("0")

        position = PositionRisk(
            symbol=symbol,
            quantity=quantity,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            max_loss_amount=loss_amount,
            max_loss_pct=loss_pct,
            risk_reward_ratio=risk_reward,
            created_at=datetime.utcnow(),
        )

        self.positions[symbol] = position
        logger.info(
            "Position registered: %s | Qty: %.4f | Risk: %.2f%% | R:R: %.2f",
            symbol,
            quantity,
            loss_pct,
            risk_reward,
        )
        return True

    def close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        realized_pnl: Decimal,
    ) -> bool:
        if symbol not in self.positions:
            return False

        position = self.positions[symbol]
        del self.positions[symbol]

        self.account_equity += realized_pnl
        if realized_pnl < 0:
            self.daily_loss += abs(realized_pnl)

        self.peak_equity = max(self.peak_equity, self.account_equity)

        logger.info(
            "Position closed: %s | P&L: %.2f | Remaining: %d positions",
            symbol,
            realized_pnl,
            len(self.positions),
        )
        return True

    def calculate_drawdown(self) -> DrawdownSnapshot:
        drawdown_amount = self.peak_equity - self.account_equity
        drawdown_pct = (drawdown_amount / self.peak_equity) * Decimal("100") if self.peak_equity > 0 else Decimal("0")
        is_breached = drawdown_pct > self.max_drawdown_pct

        snapshot = DrawdownSnapshot(
            timestamp=datetime.utcnow(),
            peak_equity=self.peak_equity,
            current_equity=self.account_equity,
            drawdown_amount=drawdown_amount,
            drawdown_pct=drawdown_pct,
            is_breached=is_breached,
        )

        self.drawdown_history.append(snapshot)
        return snapshot

    def get_risk_metrics(self) -> RiskMetrics:
        total_risk = sum(p.max_loss_amount for p in self.positions.values())
        total_risk_pct = (total_risk / self.account_equity * Decimal("100")) if self.account_equity > 0 else Decimal("0")

        drawdown = self.calculate_drawdown()
        
        breached_limits = []
        if len(self.positions) >= self.max_open_positions:
            breached_limits.append("max_positions")
        if drawdown.is_breached:
            breached_limits.append("max_drawdown")
        if total_risk_pct > (self.max_risk_per_trade_pct * Decimal("3")):
            breached_limits.append("portfolio_concentration")

        daily_loss_pct = (self.daily_loss / (self.account_equity + self.daily_loss) * Decimal("100")) if (self.account_equity + self.daily_loss) > 0 else Decimal("0")

        return RiskMetrics(
            account_equity=self.account_equity,
            total_risk_exposure=total_risk,
            total_risk_pct=total_risk_pct,
            open_positions_count=len(self.positions),
            max_position_risk=max((p.max_loss_amount for p in self.positions.values()), default=Decimal("0")),
            daily_loss_realized=self.daily_loss,
            daily_loss_pct=daily_loss_pct,
            drawdown_pct=drawdown.drawdown_pct,
            is_within_limits=len(breached_limits) == 0,
            breached_limits=breached_limits,
        )

    def reset_daily_loss(self) -> None:
        self.daily_loss = Decimal("0")
        logger.info("Daily loss counter reset")

    def get_max_position_size_available(self) -> Decimal:
        return Decimal(max(0, self.max_open_positions - len(self.positions)))
