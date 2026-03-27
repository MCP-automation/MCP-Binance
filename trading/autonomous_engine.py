"""Autonomous live/paper trading bot engine.

Each bot runs a strategy in a background asyncio task.  On every tick it:
  1. Fetches the latest N candles for the configured symbol/timeframe.
  2. Runs the chosen indicator strategy to produce a signal array.
  3. Uses the *second-to-last* candle signal (last *completed* bar) to avoid
     acting on a still-forming candle.
  4. Opens a position when a fresh signal fires (no existing position).
  5. Closes the position on SL hit, TP hit, or opposing signal.

Paper mode  → trades go to an in-memory PaperTradingSession (no real money).
Live  mode  → trades are placed via ccxt on Binance Futures.

Public surface
--------------
  BotConfig          – configuration dataclass
  BotTrade           – single trade record
  AutonomousBot      – single bot instance (start / stop / get_status)
  BotManager         – registry of all running bots
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeframe → poll-interval (seconds)
# Poll at ¼ of the candle period so we react quickly but don't spam the API.
# Minimum 15 s, maximum 3 600 s (1 h).
# ---------------------------------------------------------------------------
_TF_POLL_S: Dict[str, float] = {
    "1m":  15.0,
    "3m":  45.0,
    "5m":  75.0,
    "15m": 225.0,
    "30m": 450.0,
    "1h":  900.0,
    "2h":  1_800.0,
    "4h":  3_600.0,
    "6h":  3_600.0,
    "8h":  3_600.0,
    "12h": 3_600.0,
    "1d":  3_600.0,
}

# How many candles to look back per strategy (enough for indicators + a few extras)
_LOOKBACK: Dict[str, int] = {
    "ema_crossover":  55,
    "momentum":       45,
    "mean_reversion": 35,
    "sma_crossover":  65,
    "btc_trend":      250,
    "btc_trend_v2":   250,
    "futures_trend":  250,
}


# ---------------------------------------------------------------------------
# Pure indicator helpers (no external dependencies)
# ---------------------------------------------------------------------------

def _ema(prices: np.ndarray, period: int) -> np.ndarray:
    result = np.zeros(len(prices))
    k = 2.0 / (period + 1)
    result[0] = prices[0]
    for i in range(1, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)
    return result


def _sma(prices: np.ndarray, period: int) -> np.ndarray:
    result = np.full(len(prices), np.nan)
    for i in range(period - 1, len(prices)):
        result[i] = float(np.mean(prices[i - period + 1: i + 1]))
    return result


def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(prices)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g  = np.zeros(len(prices))
    avg_l  = np.zeros(len(prices))
    if len(gains) >= period:
        avg_g[period] = float(np.mean(gains[:period]))
        avg_l[period] = float(np.mean(losses[:period]))
        for i in range(period + 1, len(prices)):
            avg_g[i] = (avg_g[i - 1] * (period - 1) + gains[i - 1]) / period
            avg_l[i] = (avg_l[i - 1] * (period - 1) + losses[i - 1]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_l == 0, np.inf, avg_g / avg_l)
    return np.where(avg_l == 0, 100.0, 100.0 - (100.0 / (1.0 + rs)))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BotConfig:
    symbol:            str
    timeframe:         str
    strategy:          str
    leverage:          int   = 1
    position_size_pct: float = 10.0   # % of available balance per trade
    stop_loss_pct:     float = 2.0
    take_profit_pct:   float = 4.0
    is_paper:          bool  = True


@dataclass
class BotTrade:
    trade_id:    str
    symbol:      str
    side:        str           # "LONG" | "SHORT"
    entry_price: float
    quantity:    float
    entry_time:  str
    stop_loss:   float
    take_profit: float
    exit_price:  Optional[float] = None
    exit_time:   Optional[str]   = None
    pnl:         Optional[float] = None
    status:      str             = "OPEN"   # "OPEN" | "CLOSED"
    close_reason: str            = ""


# ---------------------------------------------------------------------------
# Autonomous bot
# ---------------------------------------------------------------------------

class AutonomousBot:
    """Single strategy bot that runs in a background asyncio task.

    Callback signatures
    -------------------
    fetch_ohlcv_fn(symbol, timeframe, limit)        -> List[dict]
    place_order_fn(symbol, order_side, qty, price)  -> dict  {success, filled_price, order_id, error?}
    close_position_fn(symbol, price)                -> dict  {success, exit_price, error?}
    get_balance_fn()                                -> float  (available USDT)
    """

    def __init__(
        self,
        bot_id: str,
        config: BotConfig,
        fetch_ohlcv_fn,
        place_order_fn,
        close_position_fn,
        get_balance_fn,
        risk_manager=None,
    ) -> None:
        self.bot_id   = bot_id
        self.config   = config
        self.risk_manager = risk_manager

        self._fetch_ohlcv     = fetch_ohlcv_fn
        self._place_order     = place_order_fn
        self._close_position  = close_position_fn
        self._get_balance     = get_balance_fn

        self.state        = "STARTING"
        self.error: Optional[str] = None
        self.started_at   = datetime.utcnow().isoformat()
        self.last_tick_at: Optional[str] = None
        self.tick_count   = 0

        self.trades: List[BotTrade]              = []
        self.current_position: Optional[BotTrade] = None

        self._task:       Optional[asyncio.Task]  = None
        self._stop_event: Optional[asyncio.Event] = None
        self._signal_log: List[dict]              = []

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def _compute_signals(
        self,
        closes: np.ndarray,
        volumes: np.ndarray,
        highs: np.ndarray = None,
        lows: np.ndarray = None,
    ) -> np.ndarray:
        """Return a +1 / -1 / 0 signal array aligned with *closes*."""
        n       = len(closes)
        signals = np.zeros(n)
        strat   = self.config.strategy.lower()

        if strat in ("ema_crossover", "ema"):
            fast = _ema(closes, 9)
            slow = _ema(closes, 21)
            for i in range(21, n):
                if fast[i] > slow[i] and fast[i - 1] <= slow[i - 1]:
                    signals[i] = 1.0
                elif fast[i] < slow[i] and fast[i - 1] >= slow[i - 1]:
                    signals[i] = -1.0

        elif strat == "momentum":
            period = 20
            for i in range(period, n):
                mom = (closes[i] - closes[i - period]) / (closes[i - period] + 1e-9)
                vr  = volumes[i] / (float(np.mean(volumes[i - period: i])) + 1e-9)
                if   mom >  0.02 and vr > 1.5:
                    signals[i] =  1.0
                elif mom < -0.02 and vr > 1.5:
                    signals[i] = -1.0

        elif strat in ("mean_reversion", "rsi"):
            rsi_v = _rsi(closes, 14)
            for i in range(15, n):
                if rsi_v[i] < 30 and rsi_v[i - 1] >= 30:
                    signals[i] =  1.0
                elif rsi_v[i] > 70 and rsi_v[i - 1] <= 70:
                    signals[i] = -1.0

        elif strat in ("btc_trend", "btc_trend_v2"):
            atr_thresh = 0.008 if strat == "btc_trend" else 0.015
            vol_mult   = 1.05  if strat == "btc_trend" else 1.20
            ema50  = _ema(closes, 50)
            ema200 = _ema(closes, 200)
            if highs is not None and lows is not None:
                tr = np.maximum(highs - lows,
                     np.maximum(np.abs(highs - np.roll(closes, 1)),
                                np.abs(lows  - np.roll(closes, 1))))
                tr[0] = highs[0] - lows[0]
            else:
                tr = np.abs(np.diff(closes, prepend=closes[0]))
            atr14    = np.convolve(tr, np.ones(14) / 14, mode="full")[:n]
            rsi_arr  = _rsi(closes, 14)
            vol_ma20 = np.convolve(volumes, np.ones(20) / 20, mode="full")[:n]
            src_h = highs if highs is not None else closes
            hh20  = np.full(n, np.nan)
            for i in range(20, n):
                hh20[i] = np.max(src_h[i - 20 : i])
            for i in range(200, n):
                if np.isnan(hh20[i]) or np.isnan(rsi_arr[i]):
                    continue
                if (ema50[i] > ema200[i]
                        and (atr14[i] / (closes[i] + 1e-9)) > atr_thresh
                        and closes[i] > hh20[i]
                        and rsi_arr[i] < 70
                        and volumes[i] > vol_mult * vol_ma20[i]):
                    signals[i] = 1.0

        elif strat == "futures_trend":
            ema50  = _ema(closes, 50)
            ema200 = _ema(closes, 200)
            if highs is not None and lows is not None:
                tr = np.maximum(highs - lows,
                     np.maximum(np.abs(highs - np.roll(closes, 1)),
                                np.abs(lows  - np.roll(closes, 1))))
                tr[0] = highs[0] - lows[0]
            else:
                tr = np.abs(np.diff(closes, prepend=closes[0]))
            atr14    = np.convolve(tr, np.ones(14) / 14, mode="full")[:n]
            rsi_arr  = _rsi(closes, 14)
            vol_ma20 = np.convolve(volumes, np.ones(20) / 20, mode="full")[:n]
            src_h = highs if highs is not None else closes
            src_l = lows  if lows  is not None else closes
            hh20  = np.full(n, np.nan)
            ll20  = np.full(n, np.nan)
            for i in range(20, n):
                hh20[i] = np.max(src_h[i - 20 : i])
                ll20[i] = np.min(src_l[i - 20 : i])
            for i in range(200, n):
                if np.isnan(hh20[i]) or np.isnan(rsi_arr[i]):
                    continue
                high_atr = (atr14[i] / (closes[i] + 1e-9)) > 0.008
                high_vol = volumes[i] > 1.1 * vol_ma20[i]
                if (ema50[i] > ema200[i] and closes[i] > hh20[i]
                        and rsi_arr[i] < 70 and high_atr and high_vol):
                    signals[i] = 1.0
                elif (ema50[i] < ema200[i] and closes[i] < ll20[i]
                        and rsi_arr[i] > 30 and high_atr and high_vol):
                    signals[i] = -1.0

        else:  # sma_crossover (default fallback)
            sf = _sma(closes, 10)
            ss = _sma(closes, 30)
            for i in range(30, n):
                if not (np.isnan(sf[i]) or np.isnan(ss[i])):
                    if sf[i] > ss[i] and sf[i - 1] <= ss[i - 1]:
                        signals[i] =  1.0
                    elif sf[i] < ss[i] and sf[i - 1] >= ss[i - 1]:
                        signals[i] = -1.0

        return signals

    # ------------------------------------------------------------------
    # Tick logic
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        self.tick_count  += 1
        self.last_tick_at = datetime.utcnow().isoformat()

        lookback = _LOOKBACK.get(self.config.strategy, 55) + 10
        candles  = await self._fetch_ohlcv(self.config.symbol, self.config.timeframe, lookback)

        if len(candles) < 22:
            logger.warning("Bot %s: only %d candles — skipping tick", self.bot_id, len(candles))
            return

        closes  = np.array([float(c["close"])  for c in candles])
        volumes = np.array([float(c["volume"]) for c in candles])
        highs   = np.array([float(c["high"])   for c in candles])
        lows    = np.array([float(c["low"])    for c in candles])
        current_price = closes[-1]

        signals  = self._compute_signals(closes, volumes, highs, lows)
        last_sig = signals[-2] if len(signals) >= 2 else 0.0   # last *completed* bar
        prev_sig = signals[-3] if len(signals) >= 3 else 0.0

        # ── Check existing position for SL / TP / signal exit ──────────
        if self.current_position is not None:
            pos    = self.current_position
            sl_hit = (
                (pos.side == "LONG"  and current_price <= pos.stop_loss) or
                (pos.side == "SHORT" and current_price >= pos.stop_loss)
            )
            tp_hit = (
                (pos.side == "LONG"  and current_price >= pos.take_profit) or
                (pos.side == "SHORT" and current_price <= pos.take_profit)
            )
            sig_exit = (
                (pos.side == "LONG"  and last_sig == -1.0) or
                (pos.side == "SHORT" and last_sig ==  1.0)
            )
            close_reason = (
                "STOP_LOSS"   if sl_hit   else
                "TAKE_PROFIT" if tp_hit   else
                "SIGNAL"      if sig_exit else ""
            )
            if close_reason:
                await self._do_close(current_price, close_reason)

        # ── Open new position on a *fresh* signal (transition from 0 → ±1) ──
        if self.current_position is None and last_sig != 0.0 and prev_sig == 0.0:
            side = "LONG" if last_sig == 1.0 else "SHORT"
            await self._do_open(side, current_price)

        # Log every non-zero signal
        if last_sig != 0.0:
            entry = {
                "time":   self.last_tick_at,
                "signal": "BUY" if last_sig == 1.0 else "SELL",
                "price":  round(current_price, 6),
                "action": "OPEN_ATTEMPTED" if (last_sig != 0.0 and prev_sig == 0.0) else "HOLD",
            }
            self._signal_log.append(entry)
            if len(self._signal_log) > 200:
                self._signal_log = self._signal_log[-200:]

    # ------------------------------------------------------------------
    # Order helpers
    # ------------------------------------------------------------------

    async def _do_open(self, side: str, price: float) -> None:
        try:
            balance = await self._get_balance()
            if balance <= 0:
                logger.warning("Bot %s: zero balance — cannot open position", self.bot_id)
                return

            margin = balance * (self.config.position_size_pct / 100.0)
            qty    = (margin * self.config.leverage) / max(price, 1e-9)

            # Compute SL / TP
            sl_pct = self.config.stop_loss_pct  / 100.0
            tp_pct = self.config.take_profit_pct / 100.0
            if side == "LONG":
                sl = price * (1.0 - sl_pct)
                tp = price * (1.0 + tp_pct)
            else:
                sl = price * (1.0 + sl_pct)
                tp = price * (1.0 - tp_pct)

            # Optional risk-manager check (live mode only)
            if self.risk_manager is not None:
                from decimal import Decimal
                is_valid, msg, _ = await self.risk_manager.validate_order_pre_placement(
                    symbol=self.config.symbol,
                    entry_price=Decimal(str(round(price, 8))),
                    stop_loss_price=Decimal(str(round(sl, 8))),
                    quantity=Decimal(str(round(qty, 8))),
                )
                if not is_valid:
                    logger.warning("Bot %s: risk check blocked order — %s", self.bot_id, msg)
                    return

            order_side = "BUY" if side == "LONG" else "SELL"
            result = await self._place_order(self.config.symbol, order_side, qty, price)

            if not result.get("success", False):
                logger.error(
                    "Bot %s: open order failed — %s", self.bot_id, result.get("error", "unknown")
                )
                return

            fill = float(result.get("filled_price", price))
            # Recompute SL/TP from actual fill
            if side == "LONG":
                sl = fill * (1.0 - sl_pct)
                tp = fill * (1.0 + tp_pct)
            else:
                sl = fill * (1.0 + sl_pct)
                tp = fill * (1.0 - tp_pct)

            trade = BotTrade(
                trade_id=str(uuid.uuid4())[:8],
                symbol=self.config.symbol,
                side=side,
                entry_price=fill,
                quantity=qty,
                entry_time=datetime.utcnow().isoformat(),
                stop_loss=sl,
                take_profit=tp,
            )
            self.current_position = trade
            self.trades.append(trade)
            logger.info(
                "Bot %s: OPEN %s %s qty=%.6f @ %.6f  SL=%.6f  TP=%.6f",
                self.bot_id, side, self.config.symbol, qty, fill, sl, tp,
            )

        except Exception as e:
            logger.error("Bot %s: _do_open error — %s", self.bot_id, str(e)[:200])

    async def _do_close(self, price: float, reason: str) -> None:
        try:
            result = await self._close_position(self.config.symbol, price)
            actual = (
                float(result.get("exit_price", price))
                if result.get("success") else price
            )

            pos    = self.current_position
            margin = pos.quantity * pos.entry_price / max(self.config.leverage, 1)
            pct_chg = (
                (actual - pos.entry_price) / pos.entry_price
                if pos.side == "LONG"
                else (pos.entry_price - actual) / pos.entry_price
            )
            pnl = pct_chg * self.config.leverage * margin

            pos.exit_price   = actual
            pos.exit_time    = datetime.utcnow().isoformat()
            pos.pnl          = round(pnl, 6)
            pos.status       = "CLOSED"
            pos.close_reason = reason
            self.current_position = None

            logger.info(
                "Bot %s: CLOSE %s %s @ %.6f  pnl=%.4f  reason=%s",
                self.bot_id, pos.side, pos.symbol, actual, pnl, reason,
            )

        except Exception as e:
            logger.error("Bot %s: _do_close error — %s", self.bot_id, str(e)[:200])

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        self.state   = "RUNNING"
        poll_secs    = _TF_POLL_S.get(self.config.timeframe, 900.0)

        logger.info(
            "Bot %s STARTED  symbol=%s  tf=%s  strategy=%s  lev=%dx  paper=%s  poll=%.0fs",
            self.bot_id, self.config.symbol, self.config.timeframe,
            self.config.strategy, self.config.leverage, self.config.is_paper, poll_secs,
        )

        try:
            while not self._stop_event.is_set():
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception as tick_err:
                    logger.error("Bot %s: tick error — %s", self.bot_id, str(tick_err)[:200])
                    self.error = str(tick_err)[:200]

                # Wait poll_secs OR until stop is requested
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()),
                        timeout=poll_secs,
                    )
                except asyncio.TimeoutError:
                    pass   # Normal — time to do next tick

        except asyncio.CancelledError:
            logger.info("Bot %s: task cancelled", self.bot_id)
        except Exception as fatal:
            self.state = "ERROR"
            self.error = str(fatal)[:300]
            logger.error("Bot %s: fatal error — %s", self.bot_id, str(fatal)[:300])
            return

        self.state = "STOPPED"
        logger.info("Bot %s: STOPPED", self.bot_id)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the stop-event (requires running event loop) and launch task."""
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run_loop(), name=f"autonomous-bot-{self.bot_id}"
        )

    async def stop(self) -> None:
        """Signal the loop to stop and await task completion (up to 5 s)."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self.state = "STOPPED"

    # ------------------------------------------------------------------
    # Status reporting
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        closed     = [t for t in self.trades if t.status == "CLOSED"]
        total_pnl  = sum(t.pnl for t in closed if t.pnl is not None)
        wins       = sum(1 for t in closed if (t.pnl or 0.0) > 0)
        recent_trades = [
            {
                "trade_id":    t.trade_id,
                "side":        t.side,
                "entry_price": round(t.entry_price, 6),
                "exit_price":  round(t.exit_price, 6) if t.exit_price else None,
                "pnl":         t.pnl,
                "close_reason": t.close_reason,
                "entry_time":  t.entry_time,
                "exit_time":   t.exit_time,
            }
            for t in self.trades[-20:]
        ]
        return {
            "bot_id":      self.bot_id,
            "state":       self.state,
            "symbol":      self.config.symbol,
            "timeframe":   self.config.timeframe,
            "strategy":    self.config.strategy,
            "leverage":    self.config.leverage,
            "position_size_pct": self.config.position_size_pct,
            "stop_loss_pct":     self.config.stop_loss_pct,
            "take_profit_pct":   self.config.take_profit_pct,
            "is_paper":    self.config.is_paper,
            "started_at":  self.started_at,
            "last_tick_at": self.last_tick_at,
            "tick_count":  self.tick_count,
            "error":       self.error,
            "current_position": (
                {
                    "side":        self.current_position.side,
                    "entry_price": round(self.current_position.entry_price, 6),
                    "quantity":    round(self.current_position.quantity, 6),
                    "stop_loss":   round(self.current_position.stop_loss, 6),
                    "take_profit": round(self.current_position.take_profit, 6),
                    "entry_time":  self.current_position.entry_time,
                }
                if self.current_position else None
            ),
            "stats": {
                "total_trades":  len(closed),
                "wins":          wins,
                "losses":        len(closed) - wins,
                "win_rate":      round(wins / len(closed) * 100, 1) if closed else 0.0,
                "total_pnl":     round(total_pnl, 4),
            },
            "recent_trades":  recent_trades,
            "recent_signals": self._signal_log[-10:],
        }


# ---------------------------------------------------------------------------
# Bot manager
# ---------------------------------------------------------------------------

class BotManager:
    """Registry for all running AutonomousBot instances."""

    def __init__(self) -> None:
        self._bots: Dict[str, AutonomousBot] = {}

    def get(self, bot_id: str) -> Optional[AutonomousBot]:
        return self._bots.get(bot_id)

    def add(self, bot: AutonomousBot) -> None:
        self._bots[bot.bot_id] = bot

    async def remove(self, bot_id: str) -> bool:
        bot = self._bots.pop(bot_id, None)
        if bot is None:
            return False
        await bot.stop()
        return True

    async def stop_all(self) -> None:
        for bot in list(self._bots.values()):
            await bot.stop()
        self._bots.clear()

    def list_bots(self) -> List[dict]:
        return [bot.get_status() for bot in self._bots.values()]

    def count(self) -> int:
        return len(self._bots)
