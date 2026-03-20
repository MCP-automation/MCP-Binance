import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from exchange.types import OHLCV, MarketType
from backtesting import (
    EventDrivenBacktestEngine,
    BacktestSignal,
    BacktestSignalType,
    PerformanceMetricsCalculator,
    StrategyConfigBuilder,
    StrategyExecutor,
)


class TestEventDrivenBacktestEngine:
    def test_initialization(self):
        engine = EventDrivenBacktestEngine(initial_capital=Decimal("10000"))
        assert engine.current_equity == Decimal("10000")
        assert engine.peak_equity == Decimal("10000")
        assert len(engine.open_positions) == 0
        assert len(engine.closed_trades) == 0

    def test_enter_long_position(self):
        engine = EventDrivenBacktestEngine(initial_capital=Decimal("10000"))
        
        candle = OHLCV(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow(),
            open=Decimal("30000"),
            high=Decimal("30100"),
            low=Decimal("29900"),
            close=Decimal("30050"),
            volume=Decimal("100"),
        )
        
        signal = BacktestSignal(
            timestamp=candle.timestamp,
            symbol="BTCUSDT",
            signal_type=BacktestSignalType.BUY,
            price=Decimal("30000"),
            quantity=Decimal("0.1"),
            metadata={"stop_loss": Decimal("29400"), "take_profit": Decimal("31500")},
        )
        
        result = engine.process_bar(candle, signal)
        assert result is not None
        assert "BTCUSDT" in engine.open_positions
        assert engine.current_equity < Decimal("10000")

    def test_exit_position_with_profit(self):
        engine = EventDrivenBacktestEngine(initial_capital=Decimal("10000"))
        
        entry_candle = OHLCV(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow(),
            open=Decimal("30000"),
            high=Decimal("30100"),
            low=Decimal("29900"),
            close=Decimal("30000"),
            volume=Decimal("100"),
        )
        
        entry_signal = BacktestSignal(
            timestamp=entry_candle.timestamp,
            symbol="BTCUSDT",
            signal_type=BacktestSignalType.BUY,
            price=Decimal("30000"),
            quantity=Decimal("0.1"),
        )
        
        engine.process_bar(entry_candle, entry_signal)
        
        exit_candle = OHLCV(
            symbol="BTCUSDT",
            timestamp=entry_candle.timestamp + timedelta(hours=1),
            open=Decimal("31000"),
            high=Decimal("31200"),
            low=Decimal("30900"),
            close=Decimal("31000"),
            volume=Decimal("100"),
        )
        
        exit_signal = BacktestSignal(
            timestamp=exit_candle.timestamp,
            symbol="BTCUSDT",
            signal_type=BacktestSignalType.SELL,
            price=Decimal("31000"),
            quantity=Decimal("0.1"),
            metadata={"reason": "TAKE_PROFIT"},
        )
        
        engine.process_bar(exit_candle, exit_signal)
        
        assert "BTCUSDT" not in engine.open_positions
        assert len(engine.closed_trades) == 1
        assert engine.closed_trades[0].realized_pnl > 0

    def test_stop_loss_enforcement(self):
        engine = EventDrivenBacktestEngine(initial_capital=Decimal("10000"))
        
        entry_candle = OHLCV(
            symbol="ETHUSDT",
            timestamp=datetime.utcnow(),
            open=Decimal("2000"),
            high=Decimal("2050"),
            low=Decimal("1950"),
            close=Decimal("2000"),
            volume=Decimal("100"),
        )
        
        entry_signal = BacktestSignal(
            timestamp=entry_candle.timestamp,
            symbol="ETHUSDT",
            signal_type=BacktestSignalType.BUY,
            price=Decimal("2000"),
            quantity=Decimal("1"),
            metadata={"stop_loss": Decimal("1960"), "take_profit": Decimal("2100")},
        )
        
        engine.process_bar(entry_candle, entry_signal)
        
        stop_candle = OHLCV(
            symbol="ETHUSDT",
            timestamp=entry_candle.timestamp + timedelta(hours=1),
            open=Decimal("1950"),
            high=Decimal("1960"),
            low=Decimal("1940"),
            close=Decimal("1950"),
            volume=Decimal("100"),
        )
        
        engine.process_bar(stop_candle)
        
        assert "ETHUSDT" not in engine.open_positions
        assert len(engine.closed_trades) == 1

    def test_max_positions_limit(self):
        engine = EventDrivenBacktestEngine(initial_capital=Decimal("100000"), max_positions=2)
        
        for i in range(3):
            candle = OHLCV(
                symbol=f"BTC{i}",
                timestamp=datetime.utcnow() + timedelta(hours=i),
                open=Decimal("30000"),
                high=Decimal("30100"),
                low=Decimal("29900"),
                close=Decimal("30000"),
                volume=Decimal("100"),
            )
            
            signal = BacktestSignal(
                timestamp=candle.timestamp,
                symbol=f"BTC{i}",
                signal_type=BacktestSignalType.BUY,
                price=Decimal("30000"),
                quantity=Decimal("0.01"),
            )
            
            engine.process_bar(candle, signal)
        
        assert len(engine.open_positions) == 2

    def test_equity_tracking(self):
        engine = EventDrivenBacktestEngine(initial_capital=Decimal("10000"))
        
        entry_candle = OHLCV(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow(),
            open=Decimal("30000"),
            high=Decimal("30100"),
            low=Decimal("29900"),
            close=Decimal("30000"),
            volume=Decimal("100"),
        )
        
        entry_signal = BacktestSignal(
            timestamp=entry_candle.timestamp,
            symbol="BTCUSDT",
            signal_type=BacktestSignalType.BUY,
            price=Decimal("30000"),
            quantity=Decimal("0.1"),
        )
        
        initial_equity = engine.current_equity
        engine.process_bar(entry_candle, entry_signal)
        
        assert engine.current_equity < initial_equity


class TestPerformanceMetricsCalculator:
    def test_initialization(self):
        calc = PerformanceMetricsCalculator(risk_free_rate_pct=Decimal("2"))
        assert calc.risk_free_rate_pct == Decimal("2")

    def test_cagr_calculation(self):
        calc = PerformanceMetricsCalculator()
        
        initial = Decimal("10000")
        final = Decimal("15000")
        start = datetime(2023, 1, 1)
        end = datetime(2024, 1, 1)
        
        cagr = calc._calculate_cagr(initial, final, start, end)
        assert cagr > 0
        assert cagr < Decimal("100")

    def test_max_drawdown_calculation(self):
        calc = PerformanceMetricsCalculator()
        
        equity_values = [
            Decimal("10000"),
            Decimal("12000"),
            Decimal("11000"),
            Decimal("9000"),
            Decimal("10500"),
        ]
        
        max_dd = calc._calculate_max_drawdown(equity_values)
        assert max_dd > 0
        assert max_dd < Decimal("100")

    def test_empty_metrics(self):
        calc = PerformanceMetricsCalculator()
        metrics = calc.calculate([], [], Decimal("10000"), Decimal("10000"))
        assert metrics.total_return_pct == Decimal("0")


class TestStrategyConfigBuilder:
    def test_build_strategy(self):
        builder = StrategyConfigBuilder()
        strategy = (
            builder
            .set_name("Test Strategy")
            .set_description("A test strategy")
            .set_timeframe("1h")
            .set_symbols(["BTCUSDT"])
            .set_entry_condition("current_close > previous_close")
            .set_exit_condition("current_close < previous_close")
            .set_stop_loss(Decimal("2"))
            .set_take_profit(Decimal("5"))
            .build()
        )
        
        assert strategy.name == "Test Strategy"
        assert strategy.timeframe == "1h"
        assert "BTCUSDT" in strategy.symbols

    def test_missing_required_fields(self):
        builder = StrategyConfigBuilder()
        with pytest.raises(ValueError):
            builder.build()


class TestStrategyExecutor:
    def test_entry_signal_evaluation(self):
        builder = StrategyConfigBuilder()
        strategy = (
            builder
            .set_name("Test")
            .set_timeframe("1h")
            .set_symbols(["BTCUSDT"])
            .set_entry_condition("current_close > previous_close")
            .set_exit_condition("current_close < previous_close")
            .build()
        )
        
        executor = StrategyExecutor(strategy)
        
        candle1 = OHLCV(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow(),
            open=Decimal("30000"),
            high=Decimal("30100"),
            low=Decimal("29900"),
            close=Decimal("30000"),
            volume=Decimal("100"),
        )
        
        candle2 = OHLCV(
            symbol="BTCUSDT",
            timestamp=datetime.utcnow() + timedelta(hours=1),
            open=Decimal("30000"),
            high=Decimal("30100"),
            low=Decimal("29900"),
            close=Decimal("30100"),
            volume=Decimal("100"),
        )
        
        candles_dict = {"BTCUSDT": [candle1, candle2]}
        signals = executor.evaluate_entry(candles_dict)
        
        assert len(signals) > 0
