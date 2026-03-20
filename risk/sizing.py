from __future__ import annotations
import logging
from decimal import Decimal, ROUND_DOWN
from enum import Enum
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class SizingMethod(Enum):
    FIXED_PERCENTAGE = "FIXED_PERCENTAGE"
    KELLY_CRITERION = "KELLY_CRITERION"
    VOLATILITY_BASED = "VOLATILITY_BASED"
    ATR_BASED = "ATR_BASED"


@dataclass
class SizingResult:
    symbol: str
    method: SizingMethod
    quantity: Decimal
    risk_amount: Decimal
    reasoning: str


class FixedPercentageSizer:
    def __init__(self, risk_pct: Decimal = Decimal("2")):
        if not (Decimal("0.1") <= risk_pct <= Decimal("5")):
            raise ValueError("risk_pct must be between 0.1 and 5")
        self.risk_pct = risk_pct

    def calculate(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        account_equity: Decimal,
    ) -> SizingResult:
        if entry_price <= 0 or account_equity <= 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.FIXED_PERCENTAGE,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Invalid entry_price or account_equity",
            )

        risk_amount = account_equity * self.risk_pct / Decimal("100")
        loss_per_unit = abs(entry_price - stop_loss_price)

        if loss_per_unit == 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.FIXED_PERCENTAGE,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Stop loss equals entry price",
            )

        quantity = (risk_amount / loss_per_unit).quantize(
            Decimal("0.0001"),
            rounding=ROUND_DOWN,
        )

        return SizingResult(
            symbol=symbol,
            method=SizingMethod.FIXED_PERCENTAGE,
            quantity=quantity,
            risk_amount=risk_amount,
            reasoning=f"Risk {self.risk_pct}% of equity | Loss per unit: {loss_per_unit}",
        )


class KellyCriterionSizer:
    def __init__(
        self,
        kelly_fraction: Decimal = Decimal("0.25"),
        min_win_rate_pct: Decimal = Decimal("40"),
    ):
        if not (Decimal("0") < kelly_fraction <= Decimal("1")):
            raise ValueError("kelly_fraction must be between 0 and 1")
        if not (Decimal("0") < min_win_rate_pct < Decimal("100")):
            raise ValueError("min_win_rate_pct must be between 0 and 100")

        self.kelly_fraction = kelly_fraction
        self.min_win_rate_pct = min_win_rate_pct

    def calculate(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        take_profit_price: Decimal,
        account_equity: Decimal,
        win_rate_pct: Decimal = Decimal("55"),
        avg_win_loss_ratio: Decimal = Decimal("1.5"),
    ) -> SizingResult:
        if entry_price <= 0 or account_equity <= 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.KELLY_CRITERION,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Invalid entry_price or account_equity",
            )

        if win_rate_pct < self.min_win_rate_pct:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.KELLY_CRITERION,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning=f"Win rate {win_rate_pct}% below minimum {self.min_win_rate_pct}%",
            )

        win_decimal = win_rate_pct / Decimal("100")
        loss_decimal = (Decimal("100") - win_rate_pct) / Decimal("100")

        kelly_value = (
            (win_decimal * avg_win_loss_ratio - loss_decimal) / avg_win_loss_ratio
        )

        if kelly_value <= 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.KELLY_CRITERION,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning=f"Kelly formula negative: {kelly_value}",
            )

        fractional_kelly = kelly_value * self.kelly_fraction
        fractional_kelly = max(Decimal("0"), min(fractional_kelly, Decimal("0.25")))

        risk_amount = account_equity * fractional_kelly * Decimal("2") / Decimal("100")
        loss_per_unit = abs(entry_price - stop_loss_price)

        if loss_per_unit == 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.KELLY_CRITERION,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Stop loss equals entry price",
            )

        quantity = (risk_amount / loss_per_unit).quantize(
            Decimal("0.0001"),
            rounding=ROUND_DOWN,
        )

        return SizingResult(
            symbol=symbol,
            method=SizingMethod.KELLY_CRITERION,
            quantity=quantity,
            risk_amount=risk_amount,
            reasoning=f"Kelly: {kelly_value:.4f} | Fractional: {fractional_kelly:.4f} | Win rate: {win_rate_pct}%",
        )


class VolatilityBasedSizer:
    def __init__(
        self,
        target_risk_pct: Decimal = Decimal("2"),
        volatility_scalar: Decimal = Decimal("1.5"),
    ):
        if not (Decimal("0.1") <= target_risk_pct <= Decimal("5")):
            raise ValueError("target_risk_pct must be between 0.1 and 5")
        self.target_risk_pct = target_risk_pct
        self.volatility_scalar = volatility_scalar

    def calculate(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        account_equity: Decimal,
        atr: Decimal,
    ) -> SizingResult:
        if entry_price <= 0 or account_equity <= 0 or atr <= 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.VOLATILITY_BASED,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Invalid entry_price, account_equity, or ATR",
            )

        volatility_ratio = atr / entry_price
        adjusted_risk_pct = self.target_risk_pct / (self.volatility_scalar * volatility_ratio)
        adjusted_risk_pct = max(Decimal("0.5"), min(adjusted_risk_pct, Decimal("4")))

        risk_amount = account_equity * adjusted_risk_pct / Decimal("100")
        loss_per_unit = abs(entry_price - stop_loss_price)

        if loss_per_unit == 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.VOLATILITY_BASED,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Stop loss equals entry price",
            )

        quantity = (risk_amount / loss_per_unit).quantize(
            Decimal("0.0001"),
            rounding=ROUND_DOWN,
        )

        return SizingResult(
            symbol=symbol,
            method=SizingMethod.VOLATILITY_BASED,
            quantity=quantity,
            risk_amount=risk_amount,
            reasoning=f"Volatility ratio: {volatility_ratio:.4f} | Adjusted risk: {adjusted_risk_pct:.2f}%",
        )


class ATRBasedSizer:
    def __init__(
        self,
        atr_multiplier: Decimal = Decimal("2.5"),
        max_risk_pct: Decimal = Decimal("3"),
    ):
        if atr_multiplier <= 0:
            raise ValueError("atr_multiplier must be positive")
        self.atr_multiplier = atr_multiplier
        self.max_risk_pct = max_risk_pct

    def calculate(
        self,
        symbol: str,
        entry_price: Decimal,
        account_equity: Decimal,
        atr: Decimal,
    ) -> SizingResult:
        if entry_price <= 0 or account_equity <= 0 or atr <= 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.ATR_BASED,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Invalid entry_price, account_equity, or ATR",
            )

        stop_loss_price = entry_price - (atr * self.atr_multiplier)
        loss_per_unit = entry_price - stop_loss_price

        if loss_per_unit <= 0:
            return SizingResult(
                symbol=symbol,
                method=SizingMethod.ATR_BASED,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning="Calculated stop loss invalid",
            )

        risk_amount = account_equity * self.max_risk_pct / Decimal("100")
        quantity = (risk_amount / loss_per_unit).quantize(
            Decimal("0.0001"),
            rounding=ROUND_DOWN,
        )

        return SizingResult(
            symbol=symbol,
            method=SizingMethod.ATR_BASED,
            quantity=quantity,
            risk_amount=risk_amount,
            reasoning=f"ATR: {atr} | Multiplier: {self.atr_multiplier} | SL: {stop_loss_price}",
        )


class AdaptivePositionSizer:
    def __init__(
        self,
        default_method: SizingMethod = SizingMethod.FIXED_PERCENTAGE,
    ):
        self.default_method = default_method
        self.fixed_sizer = FixedPercentageSizer()
        self.kelly_sizer = KellyCriterionSizer()
        self.volatility_sizer = VolatilityBasedSizer()
        self.atr_sizer = ATRBasedSizer()

    def calculate(
        self,
        symbol: str,
        entry_price: Decimal,
        stop_loss_price: Decimal,
        account_equity: Decimal,
        method: Optional[SizingMethod] = None,
        **kwargs,
    ) -> SizingResult:
        method = method or self.default_method

        try:
            if method == SizingMethod.FIXED_PERCENTAGE:
                return self.fixed_sizer.calculate(
                    symbol,
                    entry_price,
                    stop_loss_price,
                    account_equity,
                )

            elif method == SizingMethod.KELLY_CRITERION:
                return self.kelly_sizer.calculate(
                    symbol,
                    entry_price,
                    stop_loss_price,
                    kwargs.get("take_profit_price", entry_price),
                    account_equity,
                    kwargs.get("win_rate_pct", Decimal("55")),
                    kwargs.get("avg_win_loss_ratio", Decimal("1.5")),
                )

            elif method == SizingMethod.VOLATILITY_BASED:
                atr = kwargs.get("atr", Decimal("0"))
                return self.volatility_sizer.calculate(
                    symbol,
                    entry_price,
                    stop_loss_price,
                    account_equity,
                    atr,
                )

            elif method == SizingMethod.ATR_BASED:
                atr = kwargs.get("atr", Decimal("0"))
                return self.atr_sizer.calculate(
                    symbol,
                    entry_price,
                    account_equity,
                    atr,
                )

        except Exception as e:
            logger.error("Error calculating position size: %s", str(e)[:100])
            return SizingResult(
                symbol=symbol,
                method=method,
                quantity=Decimal("0"),
                risk_amount=Decimal("0"),
                reasoning=f"Calculation error: {str(e)[:50]}",
            )

        return SizingResult(
            symbol=symbol,
            method=method,
            quantity=Decimal("0"),
            risk_amount=Decimal("0"),
            reasoning="Unknown sizing method",
        )
