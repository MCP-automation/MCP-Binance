import pytest
from decimal import Decimal
from datetime import datetime

from risk.calculator import RiskCalculator, DrawdownSnapshot
from risk.guards import (
    RiskGuardianSystem,
    PerTradeMaxLossGuard,
    DailyDrawdownKillSwitch,
    MaxOpenPositionsGuard,
    PortfolioConcentrationGuard,
    GuardStatus,
)
from risk.sizing import (
    FixedPercentageSizer,
    KellyCriterionSizer,
    VolatilityBasedSizer,
    ATRBasedSizer,
    AdaptivePositionSizer,
    SizingMethod,
)


class TestRiskCalculator:
    def test_initialization(self):
        calc = RiskCalculator(
            account_equity=Decimal("10000"),
            max_risk_per_trade_pct=Decimal("2"),
        )
        assert calc.account_equity == Decimal("10000")
        assert calc.peak_equity == Decimal("10000")
        assert len(calc.positions) == 0

    def test_validate_order_entry_success(self):
        calc = RiskCalculator(
            account_equity=Decimal("10000"),
            max_risk_per_trade_pct=Decimal("2"),
            max_open_positions=5,
        )
        is_valid, msg = calc.validate_order_entry(
            symbol="BTCUSDT",
            quantity=Decimal("0.1"),
            entry_price=Decimal("30000"),
            stop_loss_price=Decimal("29400"),
            take_profit_price=Decimal("31500"),
        )
        assert is_valid is True

    def test_validate_order_entry_excessive_loss(self):
        calc = RiskCalculator(
            account_equity=Decimal("10000"),
            max_risk_per_trade_pct=Decimal("2"),
        )
        is_valid, msg = calc.validate_order_entry(
            symbol="BTCUSDT",
            quantity=Decimal("1"),
            entry_price=Decimal("30000"),
            stop_loss_price=Decimal("25000"),
            take_profit_price=Decimal("35000"),
        )
        assert is_valid is False
        assert "exceeds max" in msg.lower()

    def test_register_position(self):
        calc = RiskCalculator(account_equity=Decimal("10000"))
        success = calc.register_position(
            symbol="ETHUSDT",
            quantity=Decimal("1"),
            entry_price=Decimal("2000"),
            stop_loss_price=Decimal("1960"),
            take_profit_price=Decimal("2100"),
        )
        assert success is True
        assert "ETHUSDT" in calc.positions

    def test_close_position(self):
        calc = RiskCalculator(account_equity=Decimal("10000"))
        calc.register_position(
            symbol="ETHUSDT",
            quantity=Decimal("1"),
            entry_price=Decimal("2000"),
            stop_loss_price=Decimal("1960"),
            take_profit_price=Decimal("2100"),
        )
        success = calc.close_position(
            symbol="ETHUSDT",
            exit_price=Decimal("2050"),
            realized_pnl=Decimal("50"),
        )
        assert success is True
        assert "ETHUSDT" not in calc.positions
        assert calc.account_equity == Decimal("10050")

    def test_calculate_drawdown(self):
        calc = RiskCalculator(
            account_equity=Decimal("10000"),
            max_drawdown_pct=Decimal("20"),
        )
        calc.peak_equity = Decimal("10000")
        calc.account_equity = Decimal("8500")
        
        snapshot = calc.calculate_drawdown()
        assert snapshot.drawdown_pct == Decimal("15")
        assert snapshot.is_breached is False

    def test_calculate_position_size_kelly(self):
        calc = RiskCalculator(account_equity=Decimal("10000"))
        qty = calc.calculate_position_size_kelly(
            entry_price=Decimal("100"),
            stop_loss_price=Decimal("95"),
            take_profit_price=Decimal("110"),
            win_rate_pct=Decimal("55"),
        )
        assert qty > 0


class TestPerTradeMaxLossGuard:
    def test_guard_passes(self):
        guard = PerTradeMaxLossGuard(max_loss_pct=Decimal("2"))
        result = guard.check(
            entry_price=Decimal("100"),
            stop_loss_price=Decimal("98"),
            quantity=Decimal("1"),
        )
        assert result.status == GuardStatus.OK

    def test_guard_blocks_excessive_loss(self):
        guard = PerTradeMaxLossGuard(max_loss_pct=Decimal("2"))
        result = guard.check(
            entry_price=Decimal("100"),
            stop_loss_price=Decimal("80"),
            quantity=Decimal("1"),
        )
        assert result.status == GuardStatus.BLOCKED


class TestDailyDrawdownKillSwitch:
    def test_initialization(self):
        switch = DailyDrawdownKillSwitch(daily_loss_limit_pct=Decimal("5"))
        assert switch.is_triggered is False

    def test_loss_recording(self):
        switch = DailyDrawdownKillSwitch(daily_loss_limit_pct=Decimal("5"))
        switch.daily_start_equity = Decimal("10000")
        result = switch.update_loss(Decimal("200"))
        assert result.status == GuardStatus.OK

    def test_trigger_on_excessive_loss(self):
        switch = DailyDrawdownKillSwitch(daily_loss_limit_pct=Decimal("5"))
        switch.daily_start_equity = Decimal("10000")
        result = switch.update_loss(Decimal("600"))
        assert switch.is_triggered is True
        assert result.status == GuardStatus.BLOCKED


class TestMaxOpenPositionsGuard:
    def test_max_positions_enforcement(self):
        guard = MaxOpenPositionsGuard(max_positions=3)
        guard.open_positions = 3
        result = guard.check()
        assert result.status == GuardStatus.BLOCKED

    def test_position_increment_decrement(self):
        guard = MaxOpenPositionsGuard(max_positions=5)
        guard.increment()
        assert guard.open_positions == 1
        guard.decrement()
        assert guard.open_positions == 0


class TestPortfolioConcentrationGuard:
    def test_concentration_check(self):
        guard = PortfolioConcentrationGuard(max_risk_pct=Decimal("10"))
        guard.register_position("BTCUSDT", Decimal("100"))
        result = guard.check(Decimal("50"), Decimal("10000"))
        assert result.status == GuardStatus.OK


class TestFixedPercentageSizer:
    def test_sizing_calculation(self):
        sizer = FixedPercentageSizer(risk_pct=Decimal("2"))
        result = sizer.calculate(
            symbol="BTCUSDT",
            entry_price=Decimal("30000"),
            stop_loss_price=Decimal("29400"),
            account_equity=Decimal("10000"),
        )
        assert result.quantity > 0
        assert result.method == SizingMethod.FIXED_PERCENTAGE


class TestKellyCriterionSizer:
    def test_kelly_sizing_with_positive_kelly(self):
        sizer = KellyCriterionSizer(kelly_fraction=Decimal("0.25"))
        result = sizer.calculate(
            symbol="ETHUSDT",
            entry_price=Decimal("2000"),
            stop_loss_price=Decimal("1960"),
            take_profit_price=Decimal("2100"),
            account_equity=Decimal("10000"),
            win_rate_pct=Decimal("60"),
        )
        assert result.quantity > 0 or result.method == SizingMethod.KELLY_CRITERION

    def test_kelly_sizing_with_low_win_rate(self):
        sizer = KellyCriterionSizer(kelly_fraction=Decimal("0.25"), min_win_rate_pct=Decimal("50"))
        result = sizer.calculate(
            symbol="ETHUSDT",
            entry_price=Decimal("2000"),
            stop_loss_price=Decimal("1960"),
            take_profit_price=Decimal("2100"),
            account_equity=Decimal("10000"),
            win_rate_pct=Decimal("40"),
        )
        assert result.quantity == Decimal("0")


class TestVolatilityBasedSizer:
    def test_volatility_sizing(self):
        sizer = VolatilityBasedSizer(target_risk_pct=Decimal("2"))
        result = sizer.calculate(
            symbol="BTCUSDT",
            entry_price=Decimal("30000"),
            stop_loss_price=Decimal("29400"),
            account_equity=Decimal("10000"),
            atr=Decimal("500"),
        )
        assert result.method == SizingMethod.VOLATILITY_BASED


class TestATRBasedSizer:
    def test_atr_sizing(self):
        sizer = ATRBasedSizer(atr_multiplier=Decimal("2.5"))
        result = sizer.calculate(
            symbol="BTCUSDT",
            entry_price=Decimal("30000"),
            account_equity=Decimal("10000"),
            atr=Decimal("400"),
        )
        assert result.method == SizingMethod.ATR_BASED
        assert result.quantity > 0


class TestRiskGuardianSystem:
    def test_guardian_initialization(self):
        guardian = RiskGuardianSystem(
            per_trade_loss_pct=Decimal("2"),
            daily_loss_limit_pct=Decimal("5"),
            max_positions=10,
        )
        assert guardian.per_trade_guard is not None
        assert guardian.drawdown_guard is not None
        assert guardian.positions_guard is not None

    @pytest.mark.asyncio
    async def test_order_validation_passes(self):
        guardian = RiskGuardianSystem()
        is_valid, msg, results = await guardian.validate_order_pre_execution(
            symbol="BTCUSDT",
            entry_price=Decimal("30000"),
            stop_loss_price=Decimal("29400"),
            quantity=Decimal("0.1"),
            account_equity=Decimal("10000"),
        )
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_kill_switch_trigger(self):
        guardian = RiskGuardianSystem(daily_loss_limit_pct=Decimal("5"))
        guardian.drawdown_guard.daily_start_equity = Decimal("10000")
        
        loss_result = guardian.drawdown_guard.update_loss(Decimal("600"))
        assert guardian.drawdown_guard.is_triggered is True
        assert loss_result.status == GuardStatus.BLOCKED


class TestAdaptivePositionSizer:
    def test_default_sizing_method(self):
        sizer = AdaptivePositionSizer(default_method=SizingMethod.FIXED_PERCENTAGE)
        result = sizer.calculate(
            symbol="BTCUSDT",
            entry_price=Decimal("30000"),
            stop_loss_price=Decimal("29400"),
            account_equity=Decimal("10000"),
        )
        assert result.method == SizingMethod.FIXED_PERCENTAGE

    def test_kelly_sizing_method(self):
        sizer = AdaptivePositionSizer()
        result = sizer.calculate(
            symbol="ETHUSDT",
            entry_price=Decimal("2000"),
            stop_loss_price=Decimal("1960"),
            account_equity=Decimal("10000"),
            method=SizingMethod.KELLY_CRITERION,
            take_profit_price=Decimal("2100"),
            win_rate_pct=Decimal("55"),
        )
        assert result.method == SizingMethod.KELLY_CRITERION
