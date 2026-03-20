import pytest
import asyncio
from decimal import Decimal
from datetime import datetime

from exchange.types import (
    MarketType,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderRequest,
    OrderStatus,
)
from exchange.http_client import UnifiedHTTPClient, BinanceAPIError
from exchange.clients.spot import SpotClient
from exchange.clients.usdm_futures import USDMFuturesClient
from exchange.clients.coinm_futures import COINMFuturesClient
from exchange.clients.margin import MarginClient
from exchange.simulator import PaperTradingEngine
from exchange.streams.manager import StreamConnectionManager


class TestUnifiedHTTPClient:
    @pytest.mark.asyncio
    async def test_client_initialization(self):
        client = UnifiedHTTPClient(
            "https://api.binance.com",
            "test_key",
            "test_secret",
        )
        await client.initialize()
        assert client.session is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_rate_limit_tracking(self):
        client = UnifiedHTTPClient(
            "https://api.binance.com",
            "test_key",
            "test_secret",
        )
        headers = {
            "x-mbx-used-weight-1m": "500",
            "x-mbx-order-count-1m": "50000",
        }
        client.rate_limiter.update_from_headers(headers)
        assert client.rate_limiter.weight_used == 500
        assert client.rate_limiter.order_count == 50000


class TestPaperTradingEngine:
    def test_initialization(self):
        engine = PaperTradingEngine(Decimal("10000"))
        assert engine.get_balance("USDT") == Decimal("10000")
        assert len(engine.positions) == 0

    def test_market_order_buy(self):
        engine = PaperTradingEngine(Decimal("10000"))
        order_req = OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        response = engine.place_order(order_req, Decimal("30000"))

        assert response.status == OrderStatus.FILLED
        assert response.filled_quantity == Decimal("0.1")
        assert engine.get_balance("USDT") < Decimal("10000")

    def test_market_order_sell(self):
        engine = PaperTradingEngine(Decimal("10000"))

        buy_order = OrderRequest(
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
        )
        engine.place_order(buy_order, Decimal("2000"))

        sell_order = OrderRequest(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
        )
        response = engine.place_order(sell_order, Decimal("2100"))

        assert response.status == OrderStatus.FILLED
        assert len(engine.get_positions()) >= 0

    def test_insufficient_balance_rejection(self):
        engine = PaperTradingEngine(Decimal("100"))
        order_req = OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.0"),
        )

        response = engine.place_order(order_req, Decimal("50000"))
        assert response.status == OrderStatus.REJECTED

    def test_cancel_order(self):
        engine = PaperTradingEngine(Decimal("10000"))
        order_req = OrderRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("20000"),
        )

        response = engine.place_order(order_req, Decimal("30000"))
        order_id = response.order_id

        cancel_response = engine.cancel_order(order_id)
        assert cancel_response.status == OrderStatus.CANCELED

    def test_get_stats(self):
        engine = PaperTradingEngine(Decimal("10000"))
        stats = engine.get_stats()

        assert stats["initial_balance"] == 10000.0
        assert stats["total_orders"] == 0
        assert stats["open_positions"] == 0


class TestStreamConnectionManager:
    @pytest.mark.asyncio
    async def test_manager_initialization(self):
        manager = StreamConnectionManager(MarketType.USDM_FUTURES)
        assert manager.market_type == MarketType.USDM_FUTURES
        assert manager.get_active_streams_count() == 0

    @pytest.mark.asyncio
    async def test_subscription_tracking(self):
        manager = StreamConnectionManager(MarketType.SPOT)
        await manager.start()

        callback_called = []

        def callback(data):
            callback_called.append(data)

        manager.subscribe("BTCUSDT@ticker", callback)
        assert "BTCUSDT@ticker" in manager._subscriptions

        manager.unsubscribe("BTCUSDT@ticker", callback)
        assert "BTCUSDT@ticker" not in manager._subscriptions

        await manager.stop()


class TestMarketTypeEnums:
    def test_market_type_values(self):
        assert MarketType.SPOT.value == "SPOT"
        assert MarketType.USDM_FUTURES.value == "USDM_FUTURES"
        assert MarketType.COINM_FUTURES.value == "COINM_FUTURES"
        assert MarketType.MARGIN.value == "MARGIN"

    def test_order_side_values(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"

    def test_order_status_values(self):
        assert OrderStatus.NEW.value == "NEW"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELED.value == "CANCELED"
