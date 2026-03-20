"""
EMA Crossover Trading Strategy
12/26 EMA crossover strategy with live signals and backtesting
"""

from __future__ import annotations
import logging

import pandas as pd
import numpy as np
from ta.trend import EMAIndicator

logger = logging.getLogger(__name__)


class EMACrossoverStrategy:
    """EMA Crossover Trading Strategy"""
    
    def __init__(self, fast_period: int = 12, slow_period: int = 26):
        self.fast_period = fast_period
        self.slow_period = slow_period
        logger.info(f"Initialized EMA strategy: {fast_period}/{slow_period}")
    
    async def get_signal(self, df: pd.DataFrame) -> dict:
        """
        Get current signal (BUY/SELL/HOLD)
        
        Args:
            df: DataFrame with 'close' column
        
        Returns:
            Signal dict with direction and strength
        """
        if len(df) < self.slow_period:
            logger.warning(f"Not enough data: {len(df)} < {self.slow_period}")
            return None
        
        df = df.copy()
        
        df["ema_fast"] = EMAIndicator(
            close=df["close"],
            window=self.fast_period
        ).ema_indicator()
        
        df["ema_slow"] = EMAIndicator(
            close=df["close"],
            window=self.slow_period
        ).ema_indicator()
        
        last_close = df["close"].iloc[-1]
        last_fast = df["ema_fast"].iloc[-1]
        last_slow = df["ema_slow"].iloc[-1]
        prev_fast = df["ema_fast"].iloc[-2]
        prev_slow = df["ema_slow"].iloc[-2]
        
        direction = None
        strength = 0
        
        # BUY signal: fast crosses above slow
        if prev_fast <= prev_slow and last_fast > last_slow:
            direction = "BUY"
            strength = min((last_fast / last_slow - 1) * 100, 1.0)
        # SELL signal: fast crosses below slow
        elif prev_fast >= prev_slow and last_fast < last_slow:
            direction = "SELL"
            strength = min((last_slow / last_fast - 1) * 100, 1.0)
        
        return {
            "direction": direction,
            "strength": strength,
            "fast_ema": float(last_fast),
            "slow_ema": float(last_slow),
            "close": float(last_close)
        } if direction else None
    
    async def backtest(self, df: pd.DataFrame) -> dict:
        """
        Run backtest on historical data
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Performance metrics
        """
        if len(df) < self.slow_period:
            return {
                "trades": 0,
                "win_rate": 0,
                "pnl": 0,
                "sharpe_ratio": 0,
                "max_drawdown": 0,
                "return_pct": 0
            }
        
        df = df.copy()
        
        df["ema_fast"] = EMAIndicator(
            close=df["close"],
            window=self.fast_period
        ).ema_indicator()
        
        df["ema_slow"] = EMAIndicator(
            close=df["close"],
            window=self.slow_period
        ).ema_indicator()
        
        # Generate signals
        df["signal"] = 0
        for i in range(1, len(df)):
            # BUY
            if df["ema_fast"].iloc[i] > df["ema_slow"].iloc[i] and \
               df["ema_fast"].iloc[i-1] <= df["ema_slow"].iloc[i-1]:
                df.loc[df.index[i], "signal"] = 1
            # SELL
            elif df["ema_fast"].iloc[i] < df["ema_slow"].iloc[i] and \
                 df["ema_fast"].iloc[i-1] >= df["ema_slow"].iloc[i-1]:
                df.loc[df.index[i], "signal"] = -1
        
        # Calculate returns
        df["returns"] = df["close"].pct_change()
        df["strategy_returns"] = df["returns"] * df["signal"].shift(1)
        df["cum_returns"] = (1 + df["strategy_returns"]).cumprod()
        
        # Metrics
        trades = len(df[df["signal"] != 0])
        winning_trades = len(df[(df["signal"] == 1) & (df["strategy_returns"] > 0)])
        win_rate = (winning_trades / trades * 100) if trades > 0 else 0
        
        total_return = (df["cum_returns"].iloc[-1] - 1) * 100
        sharpe = np.sqrt(252) * df["strategy_returns"].mean() / df["strategy_returns"].std() \
            if df["strategy_returns"].std() > 0 else 0
        
        # Max drawdown
        cummax = df["cum_returns"].cummax()
        drawdown = (df["cum_returns"] - cummax) / cummax
        max_dd = drawdown.min() * 100
        
        logger.info(f"Backtest: {trades} trades, WR={win_rate:.1f}%, Sharpe={sharpe:.2f}")
        
        return {
            "trades": int(trades),
            "win_rate": float(win_rate),
            "pnl": float(df["strategy_returns"].sum()),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(max_dd),
            "return_pct": float(total_return)
        }
