from __future__ import annotations
import logging
from typing import Optional, Any, Dict
from decimal import Decimal

from exchange.types import (
    MarketType,
    OrderRequest,
    OrderResponse,
    AccountInfo,
    Position,
    Ticker,
    OHLCV,
)
from exchange.http_client import UnifiedHTTPClient, BinanceAPIError
from exchange.clients.spot import SpotClient
from exchange.clients.usdm_futures import USDMFuturesClient
from exchange.clients.coinm_futures import COINMFuturesClient
from exchange.clients.margin import MarginClient
from exchange.streams.manager import StreamConnectionManager

logger = logging.getLogger(__name__)


class UnifiedExchangeManager:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

        self._spot_http: Optional[UnifiedHTTPClient] = None
        self._usdm_http: Optional[UnifiedHTTPClient] = None
        self._coinm_http: Optional[UnifiedHTTPClient] = None
        self._margin_http: Optional[UnifiedHTTPClient] = None

        self._spot_client: Optional[SpotClient] = None
        self._usdm_client: Optional[USDMFuturesClient] = None
        self._coinm_client: Optional[COINMFuturesClient] = None
        self._margin_client: Optional[MarginClient] = None

        self._stream_managers: Dict[MarketType, StreamConnectionManager] = {}

    async def initialize(self) -> None:
        spot_base = (
            "https://api.binance.com" if not self.testnet else "https://testnet.binance.vision"
        )
        usdm_base = (
            "https://fapi.binance.com" if not self.testnet else "https://testnet.binancefuture.com"
        )
        coinm_base = (
            "https://dapi.binance.com" if not self.testnet else "https://testnet.binance.vision"
        )
        margin_base = (
            "https://api.binance.com" if not self.testnet else "https://testnet.binance.vision"
        )

        self._spot_http = UnifiedHTTPClient(spot_base, self.api_key, self.api_secret, self.testnet)
        self._usdm_http = UnifiedHTTPClient(usdm_base, self.api_key, self.api_secret, self.testnet)
        self._coinm_http = UnifiedHTTPClient(
            coinm_base, self.api_key, self.api_secret, self.testnet
        )
        self._margin_http = UnifiedHTTPClient(
            margin_base, self.api_key, self.api_secret, self.testnet
        )

        await self._spot_http.initialize()
        await self._usdm_http.initialize()
        await self._coinm_http.initialize()
        await self._margin_http.initialize()

        self._spot_client = SpotClient(self._spot_http)
        self._usdm_client = USDMFuturesClient(self._usdm_http)
        self._coinm_client = COINMFuturesClient(self._coinm_http)
        self._margin_client = MarginClient(self._margin_http)

        for market_type in [
            MarketType.SPOT,
            MarketType.USDM_FUTURES,
            MarketType.COINM_FUTURES,
            MarketType.MARGIN,
        ]:
            manager = StreamConnectionManager(market_type)
            await manager.start()
            self._stream_managers[market_type] = manager

        logger.info("UnifiedExchangeManager initialized for all 4 market types")

    async def shutdown(self) -> None:
        for manager in self._stream_managers.values():
            await manager.stop()

        if self._spot_http:
            await self._spot_http.close()
        if self._usdm_http:
            await self._usdm_http.close()
        if self._coinm_http:
            await self._coinm_http.close()
        if self._margin_http:
            await self._margin_http.close()

        logger.info("UnifiedExchangeManager shut down")

    def get_client(self, market_type: MarketType):
        if market_type == MarketType.SPOT:
            return self._spot_client
        elif market_type == MarketType.USDM_FUTURES:
            return self._usdm_client
        elif market_type == MarketType.COINM_FUTURES:
            return self._coinm_client
        elif market_type == MarketType.MARGIN:
            return self._margin_client
        else:
            raise ValueError(f"Unknown market type: {market_type}")

    def get_stream_manager(self, market_type: MarketType) -> StreamConnectionManager:
        if market_type not in self._stream_managers:
            raise ValueError(f"Stream manager not initialized for {market_type}")
        return self._stream_managers[market_type]

    async def get_account_info(self, market_type: MarketType) -> AccountInfo:
        client = self.get_client(market_type)
        try:
            return await client.get_account_info()
        except BinanceAPIError as e:
            logger.error("Failed to get account info for %s: %s", market_type, str(e)[:200])
            raise

    async def get_exchange_info(self, market_type: MarketType) -> dict:
        client = self.get_client(market_type)
        try:
            return await client.get_exchange_info()
        except BinanceAPIError as e:
            logger.error("Failed to get exchange info for %s: %s", market_type, str(e)[:200])
            raise

    async def get_ticker(self, market_type: MarketType, symbol: str) -> Ticker:
        client = self.get_client(market_type)
        try:
            return await client.get_ticker(symbol)
        except BinanceAPIError as e:
            logger.error("Failed to get ticker for %s on %s: %s", symbol, market_type, str(e)[:200])
            raise

    async def get_klines(
        self,
        market_type: MarketType,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[OHLCV]:
        client = self.get_client(market_type)
        try:
            return await client.get_klines(symbol, interval, limit, start_time, end_time)
        except BinanceAPIError as e:
            logger.error(
                "Failed to get klines for %s on %s: %s",
                symbol,
                market_type,
                str(e)[:200],
            )
            raise

    async def get_positions(self, market_type: MarketType) -> list[Position]:
        if market_type == MarketType.SPOT:
            return []

        client = self.get_client(market_type)
        try:
            return await client.get_positions()
        except BinanceAPIError as e:
            logger.error("Failed to get positions for %s: %s", market_type, str(e)[:200])
            raise

    async def place_order(
        self,
        market_type: MarketType,
        order_req: OrderRequest,
        **kwargs,
    ) -> OrderResponse:
        client = self.get_client(market_type)
        try:
            return await client.place_order(order_req, **kwargs)
        except BinanceAPIError as e:
            logger.error(
                "Failed to place order for %s on %s: %s",
                order_req.symbol,
                market_type,
                str(e)[:200],
            )
            raise

    async def cancel_order(
        self,
        market_type: MarketType,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResponse:
        client = self.get_client(market_type)
        try:
            return await client.cancel_order(symbol, order_id, client_order_id)
        except BinanceAPIError as e:
            logger.error(
                "Failed to cancel order for %s on %s: %s",
                symbol,
                market_type,
                str(e)[:200],
            )
            raise

    async def get_order(
        self,
        market_type: MarketType,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResponse:
        client = self.get_client(market_type)
        try:
            return await client.get_order(symbol, order_id, client_order_id)
        except BinanceAPIError as e:
            logger.error(
                "Failed to get order for %s on %s: %s",
                symbol,
                market_type,
                str(e)[:200],
            )
            raise

    async def get_open_orders(
        self,
        market_type: MarketType,
        symbol: Optional[str] = None,
    ) -> list[OrderResponse]:
        client = self.get_client(market_type)
        try:
            return await client.get_open_orders(symbol)
        except BinanceAPIError as e:
            logger.error(
                "Failed to get open orders for %s: %s",
                market_type,
                str(e)[:200],
            )
            raise

    async def get_all_positions_across_markets(self) -> dict[MarketType, list[Position]]:
        result = {}
        for market_type in [MarketType.USDM_FUTURES, MarketType.COINM_FUTURES]:
            try:
                positions = await self.get_positions(market_type)
                result[market_type] = positions
            except BinanceAPIError:
                result[market_type] = []
        return result

    async def get_all_account_info(self) -> dict[MarketType, AccountInfo]:
        result = {}
        for market_type in [
            MarketType.SPOT,
            MarketType.USDM_FUTURES,
            MarketType.COINM_FUTURES,
            MarketType.MARGIN,
        ]:
            try:
                info = await self.get_account_info(market_type)
                result[market_type] = info
            except BinanceAPIError:
                result[market_type] = None
        return result
