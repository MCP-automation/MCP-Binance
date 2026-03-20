from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Callable, Any
from datetime import datetime
from decimal import Decimal
import websockets
from collections import defaultdict

from exchange.types import (
    MarketType,
    CandleStreamData,
    TradeStreamData,
    AggTradeStreamData,
    OrderUpdate,
    MarkPriceUpdate,
)

logger = logging.getLogger(__name__)


class StreamConnectionManager:
    def __init__(
        self,
        market_type: MarketType,
        max_connections: int = 10,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 5,
        heartbeat_interval: float = 30.0,
    ):
        self.market_type = market_type
        self.max_connections = max_connections
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.heartbeat_interval = heartbeat_interval

        self._base_url = self._get_base_url()
        self._subscriptions: dict[str, set[Callable]] = defaultdict(set)
        self._connections: dict[str, websockets.WebSocketClientProtocol] = {}
        self._reconnect_counts: dict[str, int] = defaultdict(int)
        self._stream_tasks: list[asyncio.Task] = []
        self._running = False

    def _get_base_url(self) -> str:
        if self.market_type == MarketType.SPOT:
            return "wss://stream.binance.com:9443/ws"
        elif self.market_type == MarketType.USDM_FUTURES:
            return "wss://fstream.binance.com/ws"
        elif self.market_type == MarketType.COINM_FUTURES:
            return "wss://dstream.binance.com/ws"
        elif self.market_type == MarketType.MARGIN:
            return "wss://stream.binance.com:9443/ws"
        else:
            raise ValueError(f"Unknown market type: {self.market_type}")

    async def start(self) -> None:
        self._running = True
        logger.info("StreamConnectionManager started for %s", self.market_type)

    async def stop(self) -> None:
        self._running = False
        for task in self._stream_tasks:
            task.cancel()
        for conn in self._connections.values():
            await conn.close()
        logger.info("StreamConnectionManager stopped")

    def subscribe(
        self,
        stream_name: str,
        callback: Callable[[dict], None],
    ) -> None:
        if stream_name not in self._subscriptions:
            self._subscriptions[stream_name] = set()
        self._subscriptions[stream_name].add(callback)
        logger.debug("Subscribed to stream: %s", stream_name)

    def unsubscribe(
        self,
        stream_name: str,
        callback: Callable[[dict], None],
    ) -> None:
        if stream_name in self._subscriptions:
            self._subscriptions[stream_name].discard(callback)
            if not self._subscriptions[stream_name]:
                del self._subscriptions[stream_name]
                logger.debug("Unsubscribed from stream: %s", stream_name)

    async def _get_or_create_connection(self, stream_name: str) -> websockets.WebSocketClientProtocol:
        if stream_name in self._connections:
            try:
                await self._connections[stream_name].ping()
                return self._connections[stream_name]
            except Exception:
                del self._connections[stream_name]
                self._reconnect_counts[stream_name] = 0

        url = f"{self._base_url}/{stream_name}"
        reconnect_count = 0

        while reconnect_count < self.max_reconnect_attempts:
            try:
                conn = await websockets.connect(url, ping_interval=self.heartbeat_interval)
                self._connections[stream_name] = conn
                self._reconnect_counts[stream_name] = 0
                logger.info("Connected to stream: %s", stream_name)
                return conn

            except Exception as e:
                reconnect_count += 1
                wait_time = self.reconnect_delay * (2 ** reconnect_count)
                logger.warning(
                    "Connection failed for %s (attempt %d/%d), retrying in %.1fs: %s",
                    stream_name,
                    reconnect_count,
                    self.max_reconnect_attempts,
                    wait_time,
                    str(e)[:100],
                )
                await asyncio.sleep(wait_time)

        raise ConnectionError(
            f"Failed to connect to {stream_name} after {self.max_reconnect_attempts} attempts"
        )

    async def _stream_listener(self, stream_name: str) -> None:
        while self._running:
            try:
                conn = await self._get_or_create_connection(stream_name)

                async for message in conn:
                    if not self._running:
                        break

                    try:
                        data = json.loads(message)
                        callbacks = self._subscriptions.get(stream_name, set())
                        for callback in callbacks:
                            try:
                                callback(data)
                            except Exception as e:
                                logger.error("Callback error for %s: %s", stream_name, str(e)[:100])

                    except json.JSONDecodeError:
                        logger.error("Invalid JSON from %s: %s", stream_name, message[:100])

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.error("Stream listener error for %s: %s", stream_name, str(e)[:100])
                    await asyncio.sleep(self.reconnect_delay)

    async def ensure_stream(self, stream_name: str) -> None:
        if not any(task.get_name() == stream_name for task in self._stream_tasks if not task.done()):
            task = asyncio.create_task(self._stream_listener(stream_name), name=stream_name)
            self._stream_tasks.append(task)
            logger.debug("Started listener task for stream: %s", stream_name)

    async def on_candle(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[CandleStreamData], None],
    ) -> None:
        stream_name = f"{symbol.lower()}@kline_{interval}"
        await self.ensure_stream(stream_name)

        def wrapper(data: dict) -> None:
            try:
                k = data.get("k", {})
                candle = CandleStreamData(
                    symbol=symbol,
                    market_type=self.market_type,
                    open_time=datetime.fromtimestamp(k["t"] / 1000),
                    open=Decimal(k["o"]),
                    high=Decimal(k["h"]),
                    low=Decimal(k["l"]),
                    close=Decimal(k["c"]),
                    volume=Decimal(k["v"]),
                    close_time=datetime.fromtimestamp(k["T"] / 1000),
                    quote_asset_volume=Decimal(k["q"]),
                    number_of_trades=int(k["n"]),
                    taker_buy_base_volume=Decimal(k["V"]),
                    taker_buy_quote_volume=Decimal(k["Q"]),
                    is_closed=k["x"],
                    event_time=datetime.fromtimestamp(data["E"] / 1000),
                )
                callback(candle)
            except Exception as e:
                logger.error("Error processing candle for %s: %s", symbol, str(e)[:100])

        self.subscribe(stream_name, wrapper)

    async def on_aggregate_trade(
        self,
        symbol: str,
        callback: Callable[[AggTradeStreamData], None],
    ) -> None:
        stream_name = f"{symbol.lower()}@aggTrade"
        await self.ensure_stream(stream_name)

        def wrapper(data: dict) -> None:
            try:
                trade = AggTradeStreamData(
                    symbol=symbol,
                    market_type=self.market_type,
                    trade_id=str(data["a"]),
                    price=Decimal(data["p"]),
                    quantity=Decimal(data["q"]),
                    first_trade_id=str(data["f"]),
                    last_trade_id=str(data["l"]),
                    timestamp=datetime.fromtimestamp(data["T"] / 1000),
                    is_buyer_maker=data["m"],
                    event_time=datetime.fromtimestamp(data["E"] / 1000),
                )
                callback(trade)
            except Exception as e:
                logger.error("Error processing aggregate trade for %s: %s", symbol, str(e)[:100])

        self.subscribe(stream_name, wrapper)

    async def on_order_update(
        self,
        callback: Callable[[OrderUpdate], None],
    ) -> None:
        stream_name = "user@execReport"
        await self.ensure_stream(stream_name)

        def wrapper(data: dict) -> None:
            try:
                order = OrderUpdate(
                    symbol=data["s"],
                    market_type=self.market_type,
                    order_id=str(data["i"]),
                    client_order_id=data["c"],
                    side=data["S"],
                    order_type=data["o"],
                    status=data["X"],
                    quantity=Decimal(data["q"]),
                    price=Decimal(data.get("p", 0)),
                    stop_price=Decimal(data.get("P", 0)),
                    filled_quantity=Decimal(data["z"]),
                    filled_quote_quantity=Decimal(data["Z"]),
                    commission=Decimal(data.get("n", 0)),
                    commission_asset=data.get("N", ""),
                    transaction_time=datetime.fromtimestamp(data["T"] / 1000),
                    event_time=datetime.fromtimestamp(data["E"] / 1000),
                    reject_reason=data.get("r"),
                    position_side=data.get("ps"),
                )
                callback(order)
            except Exception as e:
                logger.error("Error processing order update: %s", str(e)[:100])

        self.subscribe(stream_name, wrapper)

    async def on_mark_price_update(
        self,
        symbol: str,
        callback: Callable[[MarkPriceUpdate], None],
    ) -> None:
        stream_name = f"{symbol.lower()}@markPrice@1s"
        await self.ensure_stream(stream_name)

        def wrapper(data: dict) -> None:
            try:
                mark_price = MarkPriceUpdate(
                    symbol=data["s"],
                    market_type=self.market_type,
                    mark_price=Decimal(data["p"]),
                    index_price=Decimal(data["i"]),
                    estimated_settlement_price=Decimal(data["P"]),
                    funding_rate=Decimal(data["r"]),
                    next_funding_time=datetime.fromtimestamp(data["T"] / 1000),
                    event_time=datetime.fromtimestamp(data["E"] / 1000),
                )
                callback(mark_price)
            except Exception as e:
                logger.error("Error processing mark price update for %s: %s", symbol, str(e)[:100])

        self.subscribe(stream_name, wrapper)

    def get_active_streams_count(self) -> int:
        return len([t for t in self._stream_tasks if not t.done()])

    def get_active_connections_count(self) -> int:
        return len(self._connections)
