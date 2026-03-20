from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import threading

from exchange.exchange_adapter import ExchangeAdapter, TickerPrice
from core.event_bus import EventBus, EventType


logger = logging.getLogger(__name__)


@dataclass
class LiquidityLevel:
    price: float
    volume: float
    side: str  # 'bid' or 'ask'
    timestamp: datetime
    strength: float  # 0-1 score based on volume and recency


@dataclass
class PriceLevel:
    level: float
    touches: int
    last_touch: datetime
    strength: float


@dataclass
class LiquidityAnalysis:
    symbol: str
    current_price: float
    bid_liquidity: List[LiquidityLevel]
    ask_liquidity: List[LiquidityLevel]
    volume_profile: Dict[float, float]  # price -> volume
    high_24h: float
    low_24h: float
    vwap_24h: float
    volatility_24h: float
    momentum_24h: float
    timestamp: datetime = field(default_factory=datetime.now)

    def get_nearest_liquidity(
        self, side: str, max_distance_pct: float = 0.5
    ) -> Optional[LiquidityLevel]:
        """Get nearest liquidity level on specified side within max distance percentage"""
        liquidity = self.bid_liquidity if side == "bid" else self.ask_liquidity
        if not liquidity:
            return None

        current = self.current_price
        best = None
        best_distance = float("inf")

        for level in liquidity:
            distance_pct = abs(level.price - current) / current * 100
            if distance_pct <= max_distance_pct and distance_pct < best_distance:
                best_distance = distance_pct
                best = level

        return best

    def is_near_24h_high(self, threshold_pct: float = 0.1) -> bool:
        """Check if price is near 24h high"""
        return abs(self.current_price - self.high_24h) / self.high_24h * 100 <= threshold_pct

    def is_near_24h_low(self, threshold_pct: float = 0.1) -> bool:
        """Check if price is near 24h low"""
        return abs(self.current_price - self.low_24h) / self.low_24h * 100 <= threshold_pct


class LiquidityAgent:
    def __init__(self, exchange: ExchangeAdapter, event_bus: Optional[EventBus] = None):
        self.exchange = exchange
        self.event_bus = event_bus
        self._liquidity_cache: Dict[str, LiquidityAnalysis] = {}
        self._last_update: Dict[str, datetime] = {}
        self._update_interval = timedelta(seconds=30)  # Update every 30 seconds
        self._lock = threading.RLock()
        self._order_book_depth = 20  # Levels to analyze from order book

    def update_liquidity(self, symbol: str) -> Optional[LiquidityAnalysis]:
        """Update liquidity analysis for a symbol"""
        with self._lock:
            now = datetime.now()

            # Check if we need to update
            if symbol in self._last_update:
                if now - self._last_update[symbol] < self._update_interval:
                    return self._liquidity_cache.get(symbol)

            try:
                analysis = self._analyze_liquidity(symbol)
                self._liquidity_cache[symbol] = analysis
                self._last_update[symbol] = now

                # Emit event if event bus available
                if self.event_bus:
                    self.event_bus.emit(
                        EventType.SYSTEM_ERROR,  # Using SYSTEM_ERROR for now, could create LIQUIDITY_UPDATE
                        {"symbol": symbol, "analysis": analysis},
                    )

                return analysis

            except Exception as e:
                logger.error(f"Failed to update liquidity for {symbol}: {e}")
                return self._liquidity_cache.get(symbol)  # Return cached if available

    def _analyze_liquidity(self, symbol: str) -> LiquidityAnalysis:
        """Perform detailed liquidity analysis"""
        # Get current ticker
        ticker = self.exchange.get_ticker(symbol)
        current_price = ticker.last

        # Get 24h ticker for high/low
        ticker_24h = self.exchange.get_24h_ticker(symbol)
        high_24h = float(ticker_24h["highPrice"])
        low_24h = float(ticker_24h["lowPrice"])
        vwap_24h = float(ticker_24h.get("weightedAvgPrice", current_price))

        # Calculate 24h volatility
        price_change_24h = float(ticker_24h["priceChangePercent"])
        volatility_24h = abs(price_change_24h) / 100  # Simplified

        # Get order book for liquidity analysis
        # Note: Binance adapter doesn't have get_order_book yet, we'll use klines approximation
        # In a full implementation, you'd want to add get_order_book to ExchangeAdapter

        # For now, we'll approximate liquidity from recent volume and price action
        # Get recent klines to analyze volume profile
        klines = self.exchange.get_klines(
            symbol, "5m", limit=24 * 12
        )  # Last 24 hours of 5m candles

        volume_profile = {}
        total_volume = 0

        for kline in klines:
            # kline format: [open_time, open, high, low, close, volume, ...]
            high = float(kline[2])
            low = float(kline[3])
            volume = float(kline[5])

            # Distribute volume across price range
            price_range = high - low
            if price_range > 0:
                # Simple distribution - in reality you'd use volume profile calculation
                mid_price = (high + low) / 2
                volume_profile[mid_price] = volume_profile.get(mid_price, 0) + volume
                total_volume += volume

        # Normalize volume profile
        if total_volume > 0:
            for price in volume_profile:
                volume_profile[price] /= total_volume

        # Approximate bid/ask liquidity from spread and volume
        spread = ticker.ask - ticker.bid
        bid_liquidity = [
            LiquidityLevel(
                price=ticker.bid - (spread * i * 0.1),
                volume=ticker.volume_24h * (0.8 ** (i + 1)) / 10,  # Decreasing volume levels
                side="bid",
                timestamp=datetime.now(),
                strength=max(0, 1 - (i * 0.2)),
            )
            for i in range(self._order_book_depth)
        ]

        ask_liquidity = [
            LiquidityLevel(
                price=ticker.ask + (spread * i * 0.1),
                volume=ticker.volume_24h * (0.8 ** (i + 1)) / 10,
                side="ask",
                timestamp=datetime.now(),
                strength=max(0, 1 - (i * 0.2)),
            )
            for i in range(self._order_book_depth)
        ]

        # Calculate 24h momentum (price change from 24h ago)
        # We'll approximate using first kline from our data
        momentum_24h = price_change_24h  # Using the 24h change percent

        return LiquidityAnalysis(
            symbol=symbol,
            current_price=current_price,
            bid_liquidity=bid_liquidity,
            ask_liquidity=ask_liquidity,
            volume_profile=volume_profile,
            high_24h=high_24h,
            low_24h=low_24h,
            vwap_24h=vwap_24h,
            volatility_24h=volatility_24h,
            momentum_24h=momentum_24h,
            timestamp=datetime.now(),
        )

    def get_liquidity(self, symbol: str) -> Optional[LiquidityAnalysis]:
        """Get liquidity analysis for symbol (updates if needed)"""
        return self.update_liquidity(symbol)

    def get_fast_trade_opportunities(
        self, symbol: str, max_slippage_pct: float = 0.1
    ) -> List[Dict[str, Any]]:
        """Identify fast trade opportunities based on liquidity and proximity to 24h levels"""
        analysis = self.get_liquidity(symbol)
        if not analysis:
            return []

        opportunities = []

        # Check for liquidity clusters near 24h high/low
        near_high = analysis.is_near_24h_high(threshold_pct=max_slippage_pct)
        near_low = analysis.is_near_24h_low(threshold_pct=max_slippage_pct)

        # If near 24h high with good ask liquidity, consider short
        if near_high:
            ask_liq = analysis.get_nearest_liquidity("ask", max_slippage_pct)
            if ask_liq and ask_liq.strength > 0.5:
                opportunities.append(
                    {
                        "symbol": symbol,
                        "type": "SHORT",
                        "reason": f"Near 24h high ({analysis.high_24h:.2f})",
                        "entry_price": analysis.current_price,
                        "target": analysis.low_24h,  # Target toward 24h low
                        "stop_loss": analysis.high_24h * 1.005,  # Slightly above high
                        "liquidity_strength": ask_liq.strength,
                        "expected_slippage_pct": max_slippage_pct,
                        "confidence": min(0.9, ask_liq.strength + (1 - analysis.volatility_24h)),
                    }
                )

        # If near 24h low with good bid liquidity, consider long
        if near_low:
            bid_liq = analysis.get_nearest_liquidity("bid", max_slippage_pct)
            if bid_liq and bid_liq.strength > 0.5:
                opportunities.append(
                    {
                        "symbol": symbol,
                        "type": "LONG",
                        "reason": f"Near 24h low ({analysis.low_24h:.2f})",
                        "entry_price": analysis.current_price,
                        "target": analysis.high_24h,  # Target toward 24h high
                        "stop_loss": analysis.low_24h * 0.995,  # Slightly below low
                        "liquidity_strength": bid_liq.strength,
                        "expected_slippage_pct": max_slippage_pct,
                        "confidence": min(0.9, bid_liq.strength + (1 - analysis.volatility_24h)),
                    }
                )

        # Check for liquidity imbalances that might indicate short-term moves
        total_bid_volume = sum(l.volume for l in analysis.bid_liquidity[:5])  # Top 5 levels
        total_ask_volume = sum(l.volume for l in analysis.ask_liquidity[:5])

        if total_bid_volume > total_ask_volume * 1.5:  # Strong bid side
            opportunities.append(
                {
                    "symbol": symbol,
                    "type": "LONG",
                    "reason": "Strong bid side liquidity imbalance",
                    "entry_price": analysis.current_price,
                    "target": analysis.current_price * 1.002,  # Small target
                    "stop_loss": analysis.current_price * 0.998,
                    "liquidity_strength": min(
                        1.0, total_bid_volume / (total_bid_volume + total_ask_volume)
                    ),
                    "expected_slippage_pct": max_slippage_pct / 2,  # Better liquidity
                    "confidence": 0.7,
                }
            )
        elif total_ask_volume > total_bid_volume * 1.5:  # Strong ask side
            opportunities.append(
                {
                    "symbol": symbol,
                    "type": "SHORT",
                    "reason": "Strong ask side liquidity imbalance",
                    "entry_price": analysis.current_price,
                    "target": analysis.current_price * 0.998,
                    "stop_loss": analysis.current_price * 1.002,
                    "liquidity_strength": min(
                        1.0, total_ask_volume / (total_bid_volume + total_ask_volume)
                    ),
                    "expected_slippage_pct": max_slippage_pct / 2,
                    "confidence": 0.7,
                }
            )

        return opportunities

    def get_status(self) -> Dict[str, Any]:
        """Get agent status"""
        with self._lock:
            return {
                "symbols_tracked": list(self._liquidity_cache.keys()),
                "last_updates": {k: v.isoformat() for k, v in self._last_update.items()},
                "update_interval_seconds": self._update_interval.total_seconds(),
            }
