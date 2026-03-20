"""ccxt-based Binance USD-M Futures client for market data, symbol discovery, and order execution."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class CCXTFuturesClient:
    """Async ccxt Binance USD-M Futures client wrapping market-data endpoints."""

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self._exchange = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        try:
            import ccxt.async_support as ccxt  # type: ignore
            import aiohttp  # type: ignore
        except ImportError:
            raise RuntimeError("ccxt / aiohttp not installed. Run: pip install ccxt aiohttp")

        self._exchange = ccxt.binanceusdm(
            {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "future",
                    "adjustForTimeDifference": True,
                    "fetchCurrencies": False,
                },
            }
        )

        if self.testnet:
            self._exchange.set_sandbox_mode(True)

        resolver = aiohttp.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver)
        self._exchange.session = aiohttp.ClientSession(connector=connector)

        await self._exchange.load_markets()
        self._initialized = True
        logger.info("CCXTFuturesClient initialized (testnet=%s)", self.testnet)

    async def close(self) -> None:
        if self._exchange and self._initialized:
            try:
                if hasattr(self._exchange, "session") and self._exchange.session:
                    await self._exchange.session.close()
                await self._exchange.close()
            except Exception as e:
                logger.warning("Error closing CCXT client: %s", e)
            finally:
                self._initialized = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_init(self) -> None:
        if not self._initialized or not self._exchange:
            raise RuntimeError("CCXTFuturesClient not initialized. Call initialize() first.")

    def _to_ccxt_symbol(self, binance_symbol: str) -> str:
        """Convert 'BTCUSDT' → 'BTC/USDT:USDT' for ccxt."""
        self._require_init()
        # Prefer direct lookup by exchange-native symbol ID
        for market_id, market in self._exchange.markets.items():
            if market.get("id") == binance_symbol:
                return market_id
        # Heuristic fallback
        if binance_symbol.endswith("USDT"):
            return f"{binance_symbol[:-4]}/USDT:USDT"
        if binance_symbol.endswith("BUSD"):
            return f"{binance_symbol[:-4]}/BUSD:BUSD"
        return binance_symbol

    @staticmethod
    def _normalize_timeframe(tf: str) -> str:
        mapping = {
            "1m": "1m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "2h": "2h",
            "4h": "4h",
            "6h": "6h",
            "8h": "8h",
            "12h": "12h",
            "1d": "1d",
            "3d": "3d",
            "1w": "1w",
            "1M": "1M",
        }
        return mapping.get(tf, tf)

    # ------------------------------------------------------------------
    # Market-data methods
    # ------------------------------------------------------------------

    async def get_futures_symbols(self) -> List[str]:
        """Return all active USDT-settled perpetual futures symbols (Binance format)."""
        self._require_init()
        result = []
        for market in self._exchange.markets.values():
            if market.get("swap") and market.get("settle") == "USDT" and market.get("active"):
                bid = market.get("id", "")
                if bid:
                    result.append(bid)
        return sorted(result)

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """24-hour price statistics."""
        self._require_init()
        t = await self._exchange.fetch_ticker(self._to_ccxt_symbol(symbol))
        return {
            "symbol": symbol,
            "last_price": str(t.get("last") or 0),
            "bid": str(t.get("bid") or 0),
            "ask": str(t.get("ask") or 0),
            "high_24h": str(t.get("high") or 0),
            "low_24h": str(t.get("low") or 0),
            "volume": str(t.get("baseVolume") or 0),
            "quote_volume": str(t.get("quoteVolume") or 0),
            "price_change": str(t.get("change") or 0),
            "price_change_pct": str(round(float(t.get("percentage") or 0), 4)),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Order book snapshot."""
        self._require_init()
        ob = await self._exchange.fetch_order_book(self._to_ccxt_symbol(symbol), limit)
        return {
            "symbol": symbol,
            "bids": [[str(p), str(q)] for p, q in ob["bids"][:limit]],
            "asks": [[str(p), str(q)] for p, q in ob["asks"][:limit]],
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        start_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """OHLCV candle data."""
        self._require_init()
        ohlcv = await self._exchange.fetch_ohlcv(
            self._to_ccxt_symbol(symbol),
            timeframe=self._normalize_timeframe(timeframe),
            since=start_time,
            limit=min(limit, 1500),
        )
        return [
            {
                "timestamp": datetime.utcfromtimestamp(c[0] / 1000).isoformat(),
                "open": str(c[1]),
                "high": str(c[2]),
                "low": str(c[3]),
                "close": str(c[4]),
                "volume": str(c[5]),
            }
            for c in ohlcv
        ]

    async def get_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """Current funding rate."""
        self._require_init()
        f = await self._exchange.fetch_funding_rate(self._to_ccxt_symbol(symbol))
        rate = f.get("fundingRate") or 0
        return {
            "symbol": symbol,
            "funding_rate": str(rate),
            "funding_rate_pct": str(round(float(rate) * 100, 6)),
            "mark_price": str(f.get("markPrice") or 0),
            "index_price": str(f.get("indexPrice") or 0),
            "next_funding_time": (
                datetime.utcfromtimestamp(f["nextFundingTimestamp"] / 1000).isoformat()
                if f.get("nextFundingTimestamp")
                else f.get("nextFundingDatetime")
            ),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_open_interest(self, symbol: str) -> Dict[str, Any]:
        """Current open interest."""
        self._require_init()
        oi = await self._exchange.fetch_open_interest(self._to_ccxt_symbol(symbol))
        return {
            "symbol": symbol,
            "open_interest": str(oi.get("openInterest") or 0),
            "open_interest_value": str(oi.get("openInterestValue") or 0),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Recent public trades."""
        self._require_init()
        trades = await self._exchange.fetch_trades(
            self._to_ccxt_symbol(symbol), limit=min(limit, 1000)
        )
        result = []
        for t in trades:
            ts = t.get("timestamp")
            try:
                ts_iso = datetime.utcfromtimestamp(ts / 1000).isoformat() if ts else None
            except Exception:
                ts_iso = None
            result.append(
                {
                    "id": str(t.get("id") or ""),
                    "price": str(t.get("price") or 0),
                    "quantity": str(t.get("amount") or 0),
                    "side": (t.get("side") or "").upper(),
                    "is_buyer_maker": t.get("takerOrMaker") == "maker",
                    "quote_quantity": str(t.get("cost") or 0),
                    "timestamp": ts_iso,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def _build_order_response(
        self, raw: Dict[str, Any], symbol: str, side: str, order_type: str
    ) -> Any:
        """Convert a raw ccxt order dict into an OrderResponse domain object."""
        from exchange.types import OrderResponse, OrderSide, OrderType, OrderStatus

        _status_map = {
            "open": OrderStatus.NEW,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "cancelled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        _type_map = {"market": OrderType.MARKET, "limit": OrderType.LIMIT}

        return OrderResponse(
            order_id=str(raw["id"]),
            client_order_id=raw.get("clientOrderId"),
            symbol=symbol,
            side=OrderSide[side.upper()],
            order_type=_type_map.get(order_type.lower(), OrderType.MARKET),
            status=_status_map.get(str(raw.get("status", "")).lower(), OrderStatus.NEW),
            quantity=Decimal(str(raw.get("amount") or 0)),
            price=Decimal(str(raw.get("average") or raw.get("price") or 0)),
            stop_price=None,
            filled_quantity=Decimal(str(raw.get("filled") or 0)),
            filled_quote_quantity=Decimal(str(raw.get("cost") or 0)),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    async def place_market_order(self, symbol: str, side: str, quantity: float) -> Any:
        self._require_init()
        ccxt_sym = self._to_ccxt_symbol(symbol)
        qty = float(self._exchange.amount_to_precision(ccxt_sym, quantity))
        raw = await self._exchange.create_market_order(
            ccxt_sym,
            side.lower(),
            qty,
            params={"newOrderRespType": "RESULT"},
        )
        return self._build_order_response(raw, symbol, side, "market")

    async def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Any:
        self._require_init()
        ccxt_sym = self._to_ccxt_symbol(symbol)
        qty = float(self._exchange.amount_to_precision(ccxt_sym, quantity))
        price_precise = float(self._exchange.price_to_precision(ccxt_sym, price))
        raw = await self._exchange.create_limit_order(
            ccxt_sym,
            side.lower(),
            qty,
            price_precise,
        )
        return self._build_order_response(raw, symbol, side, "limit")

    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        self._require_init()
        ccxt_sym = self._to_ccxt_symbol(symbol)
        result = await self._exchange.set_leverage(leverage, ccxt_sym)
        return {
            "symbol": symbol,
            "leverage": leverage,
            "status": "ok",
            "raw": result,
        }

    async def get_usdt_balance(self) -> float:
        self._require_init()
        balance = await self._exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        return float(usdt.get("free", 0) or 0)

    async def get_account_balance(self) -> Dict[str, Any]:
        self._require_init()
        account = await self._exchange.fapiprivatev3_get_account()
        assets = []
        for a in account.get("assets", []):
            wb = float(a.get("walletBalance", 0) or 0)
            if wb > 0:
                assets.append({
                    "asset": a.get("asset", ""),
                    "wallet_balance": str(wb),
                    "unrealized_pnl": str(float(a.get("unrealizedProfit", 0) or 0)),
                    "margin_balance": str(float(a.get("marginBalance", 0) or 0)),
                    "available_balance": str(float(a.get("availableBalance", 0) or 0)),
                    "initial_margin": str(float(a.get("initialMargin", 0) or 0)),
                    "maint_margin": str(float(a.get("maintMargin", 0) or 0)),
                })
        positions = []
        for pos in account.get("positions", []):
            pa = float(pos.get("positionAmt", 0) or 0)
            if abs(pa) > 0:
                positions.append({
                    "symbol": pos.get("symbol", ""),
                    "side": "LONG" if pa > 0 else "SHORT",
                    "quantity": str(abs(pa)),
                    "entry_price": str(float(pos.get("entryPrice", 0) or 0)),
                    "unrealized_pnl": str(float(pos.get("unRealizedProfit", 0) or 0)),
                    "notional": str(abs(float(pos.get("notional", 0) or 0))),
                    "leverage": str(pos.get("leverage", 1)),
                    "liquidation_price": str(float(pos.get("liquidationPrice", 0) or 0)),
                    "mark_price": str(float(pos.get("markPrice", 0) or 0)),
                    "initial_margin": str(float(pos.get("initialMargin", 0) or 0)),
                })
        return {
            "total_wallet_balance": str(float(account.get("totalWalletBalance", 0) or 0)),
            "total_unrealized_pnl": str(float(account.get("totalUnrealizedProfit", 0) or 0)),
            "total_margin_balance": str(float(account.get("totalMarginBalance", 0) or 0)),
            "available_balance": str(float(account.get("availableBalance", 0) or 0)),
            "total_initial_margin": str(float(account.get("totalInitialMargin", 0) or 0)),
            "total_maint_margin": str(float(account.get("totalMaintMargin", 0) or 0)),
            "total_cross_wallet_balance": str(float(account.get("totalCrossWalletBalance", 0) or 0)),
            "total_position_initial_margin": str(float(account.get("totalPositionInitialMargin", 0) or 0)),
            "can_trade": account.get("canTrade", True),
            "can_deposit": account.get("canDeposit", True),
            "can_withdraw": account.get("canWithdraw", True),
            "assets": assets,
            "open_positions": positions,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel an open order by ID."""
        self._require_init()
        raw = await self._exchange.cancel_order(order_id, self._to_ccxt_symbol(symbol))
        return {
            "order_id": str(raw.get("id", order_id)),
            "symbol": symbol,
            "status": str(raw.get("status", "canceled")).upper(),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def fetch_open_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return the open futures position for *symbol*, or None if flat."""
        self._require_init()
        positions = await self._exchange.fetch_positions([self._to_ccxt_symbol(symbol)])
        for pos in positions:
            contracts = float(pos.get("contracts") or 0)
            if abs(contracts) > 0:
                return {
                    "symbol": symbol,
                    "side": str(pos.get("side", "")).upper(),
                    "quantity": abs(contracts),
                    "entry_price": str(pos.get("entryPrice") or 0),
                    "unrealized_pnl": str(pos.get("unrealizedPnl") or 0),
                }
        return None

    async def close_position_market(self, symbol: str) -> Dict[str, Any]:
        """Close an open position at market price using reduceOnly."""
        pos = await self.fetch_open_position(symbol)
        if pos is None:
            raise RuntimeError(f"No open position found for {symbol}")
        close_side = "sell" if pos["side"] == "LONG" else "buy"
        raw = await self._exchange.create_market_order(
            self._to_ccxt_symbol(symbol),
            close_side,
            pos["quantity"],
            params={"reduceOnly": True},
        )
        return {
            "order_id": str(raw.get("id", "")),
            "symbol": symbol,
            "close_side": close_side.upper(),
            "quantity": pos["quantity"],
            "entry_price": pos["entry_price"],
            "avg_price": str(raw.get("average") or raw.get("price") or 0),
            "status": str(raw.get("status", "")).upper(),
            "timestamp": datetime.utcnow().isoformat(),
        }
