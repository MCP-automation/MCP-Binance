from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional

from exchange.types import (
    MarketType,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    AccountBalance,
    AccountInfo,
    Ticker,
    OHLCV,
)
from exchange.http_client import UnifiedHTTPClient

logger = logging.getLogger(__name__)


class SpotClient:
    def __init__(self, http_client: UnifiedHTTPClient):
        self.http = http_client
        self.market_type = MarketType.SPOT

    async def get_account_info(self) -> AccountInfo:
        result = await self.http.get("/api/v3/account", signed=True)

        balances = [
            AccountBalance(
                asset=b["asset"],
                total=Decimal(b["free"]) + Decimal(b["locked"]),
                available=Decimal(b["free"]),
                on_order=Decimal(b["locked"]),
            )
            for b in result.get("balances", [])
            if Decimal(b["free"]) + Decimal(b["locked"]) > 0
        ]

        total_wallet_balance = sum(
            (bal.total for bal in balances if bal.asset in ("USDT", "BUSD", "USDC")),
            Decimal("0"),
        )

        return AccountInfo(
            market_type=self.market_type,
            balances=balances,
            total_wallet_balance=total_wallet_balance,
            total_unrealized_pnl=Decimal("0"),
            can_trade=result.get("canTrade", True),
            can_withdraw=result.get("canWithdraw", True),
            can_deposit=result.get("canDeposit", True),
            updated_at=datetime.utcnow(),
        )

    async def get_exchange_info(self) -> dict:
        result = await self.http.get("/api/v3/exchangeInfo")
        return result

    async def get_ticker(self, symbol: str) -> Ticker:
        result = await self.http.get("/api/v3/ticker/24hr", params={"symbol": symbol})

        return Ticker(
            symbol=result["symbol"],
            market_type=self.market_type,
            bid=Decimal(result.get("bidPrice", 0)),
            ask=Decimal(result.get("askPrice", 0)),
            last=Decimal(result["lastPrice"]),
            high=Decimal(result["highPrice"]),
            low=Decimal(result["lowPrice"]),
            volume=Decimal(result["volume"]),
            quote_volume=Decimal(result.get("quoteVolume") or result.get("quoteAssetVolume") or "0"),
            timestamp=datetime.fromtimestamp(result["time"] / 1000),
        )

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[OHLCV]:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        klines = await self.http.get("/api/v3/klines", params=params)

        result = []
        for k in klines:
            result.append(
                OHLCV(
                    symbol=symbol,
                    timestamp=datetime.fromtimestamp(k[0] / 1000),
                    open=Decimal(k[1]),
                    high=Decimal(k[2]),
                    low=Decimal(k[3]),
                    close=Decimal(k[4]),
                    volume=Decimal(k[5]),
                    quote_asset_volume=Decimal(k[7]),
                    number_of_trades=int(k[8]),
                    taker_buy_base_volume=Decimal(k[9]),
                    taker_buy_quote_volume=Decimal(k[10]),
                )
            )
        return result

    async def place_order(
        self,
        order_req: OrderRequest,
    ) -> OrderResponse:
        params = {
            "symbol": order_req.symbol,
            "side": order_req.side.value,
            "type": order_req.order_type.value,
            "quantity": str(order_req.quantity),
            "timeInForce": order_req.time_in_force.value,
        }

        if order_req.price:
            params["price"] = str(order_req.price)
        if order_req.stop_price:
            params["stopPrice"] = str(order_req.stop_price)
        if order_req.client_order_id:
            params["newClientOrderId"] = order_req.client_order_id

        result = await self.http.post("/api/v3/order", params=params, signed=True)

        return OrderResponse(
            order_id=str(result["orderId"]),
            client_order_id=result.get("clientOrderId"),
            symbol=result["symbol"],
            side=OrderSide(result["side"]),
            order_type=OrderType(result["type"]),
            status=OrderStatus(result["status"]),
            quantity=Decimal(result["origQty"]),
            price=Decimal(result.get("price", 0)),
            stop_price=Decimal(result.get("stopPrice", 0)) if result.get("stopPrice") else None,
            filled_quantity=Decimal(result["executedQty"]),
            filled_quote_quantity=Decimal(result.get("cummulativeQuoteQty", 0)),
            created_at=datetime.fromtimestamp(result["transactTime"] / 1000),
            updated_at=datetime.fromtimestamp(result["transactTime"] / 1000),
            fees=Decimal("0"),
            metadata=order_req.metadata,
        )

    async def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResponse:
        params = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("Either order_id or client_order_id must be provided")

        result = await self.http.delete("/api/v3/order", params=params, signed=True)

        return OrderResponse(
            order_id=str(result["orderId"]),
            client_order_id=result.get("clientOrderId"),
            symbol=result["symbol"],
            side=OrderSide(result["side"]),
            order_type=OrderType(result["type"]),
            status=OrderStatus(result["status"]),
            quantity=Decimal(result["origQty"]),
            price=Decimal(result.get("price", 0)),
            stop_price=Decimal(result.get("stopPrice", 0)) if result.get("stopPrice") else None,
            filled_quantity=Decimal(result["executedQty"]),
            filled_quote_quantity=Decimal(result.get("cummulativeQuoteQty", 0)),
            created_at=datetime.fromtimestamp(result["transactTime"] / 1000),
            updated_at=datetime.fromtimestamp(result["transactTime"] / 1000),
            fees=Decimal("0"),
        )

    async def get_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResponse:
        params = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id

        result = await self.http.get("/api/v3/order", params=params, signed=True)

        return OrderResponse(
            order_id=str(result["orderId"]),
            client_order_id=result.get("clientOrderId"),
            symbol=result["symbol"],
            side=OrderSide(result["side"]),
            order_type=OrderType(result["type"]),
            status=OrderStatus(result["status"]),
            quantity=Decimal(result["origQty"]),
            price=Decimal(result.get("price", 0)),
            stop_price=Decimal(result.get("stopPrice", 0)) if result.get("stopPrice") else None,
            filled_quantity=Decimal(result["executedQty"]),
            filled_quote_quantity=Decimal(result.get("cummulativeQuoteQty", 0)),
            created_at=datetime.fromtimestamp(result["time"] / 1000),
            updated_at=datetime.fromtimestamp(result["updateTime"] / 1000),
            fees=Decimal("0"),
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[OrderResponse]:
        params = {}
        if symbol:
            params["symbol"] = symbol

        results = await self.http.get("/api/v3/openOrders", params=params, signed=True)

        orders = []
        for result in results:
            orders.append(
                OrderResponse(
                    order_id=str(result["orderId"]),
                    client_order_id=result.get("clientOrderId"),
                    symbol=result["symbol"],
                    side=OrderSide(result["side"]),
                    order_type=OrderType(result["type"]),
                    status=OrderStatus(result["status"]),
                    quantity=Decimal(result["origQty"]),
                    price=Decimal(result.get("price", 0)),
                    stop_price=Decimal(result.get("stopPrice", 0)) if result.get("stopPrice") else None,
                    filled_quantity=Decimal(result["executedQty"]),
                    filled_quote_quantity=Decimal(result.get("cummulativeQuoteQty", 0)),
                    created_at=datetime.fromtimestamp(result["time"] / 1000),
                    updated_at=datetime.fromtimestamp(result["updateTime"] / 1000),
                    fees=Decimal("0"),
                )
            )
        return orders

    async def cancel_all_orders(self, symbol: str) -> list[OrderResponse]:
        result = await self.http.delete("/api/v3/openOrders", params={"symbol": symbol}, signed=True)

        orders = []
        for r in result:
            orders.append(
                OrderResponse(
                    order_id=str(r["orderId"]),
                    client_order_id=r.get("clientOrderId"),
                    symbol=r["symbol"],
                    side=OrderSide(r["side"]),
                    order_type=OrderType(r["type"]),
                    status=OrderStatus(r["status"]),
                    quantity=Decimal(r["origQty"]),
                    price=Decimal(r.get("price", 0)),
                    stop_price=Decimal(r.get("stopPrice", 0)) if r.get("stopPrice") else None,
                    filled_quantity=Decimal(r["executedQty"]),
                    filled_quote_quantity=Decimal(r.get("cummulativeQuoteQty", 0)),
                    created_at=datetime.fromtimestamp(r["time"] / 1000),
                    updated_at=datetime.fromtimestamp(r["updateTime"] / 1000),
                    fees=Decimal("0"),
                )
            )
        return orders
