from __future__ import annotations
import logging
from decimal import Decimal
from datetime import datetime
from typing import Optional, Literal

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
    MarginType,
)
from exchange.http_client import UnifiedHTTPClient

logger = logging.getLogger(__name__)


class MarginClient:
    def __init__(self, http_client: UnifiedHTTPClient):
        self.http = http_client
        self.market_type = MarketType.MARGIN

    async def get_account_info(self) -> AccountInfo:
        result = await self.http.get("/sapi/v1/margin/account", signed=True)

        balances = []
        for b in result.get("userAssets", []):
            total = Decimal(b["free"]) + Decimal(b["locked"])
            if total > 0:
                balances.append(
                    AccountBalance(
                        asset=b["asset"],
                        total=total,
                        available=Decimal(b["free"]),
                        on_order=Decimal(b["locked"]),
                        borrowed=Decimal(b.get("borrowed", 0)),
                        free_margin=Decimal(b.get("free", 0)),
                    )
                )

        total_wallet_balance = Decimal(result.get("totalAssetOfBtc", 0))

        return AccountInfo(
            market_type=self.market_type,
            balances=balances,
            total_wallet_balance=total_wallet_balance,
            total_unrealized_pnl=Decimal("0"),
            total_cross_margin_balance=Decimal(result.get("totalAssetOfBtc", 0)),
            can_trade=result.get("userLevel", 0) >= 1,
            can_withdraw=True,
            can_deposit=True,
            updated_at=datetime.utcnow(),
        )

    async def get_exchange_info(self) -> dict:
        result = await self.http.get("/sapi/v1/margin/all")
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
        margin_type: Literal["MARGIN", "ISOLATED"] = "MARGIN",
    ) -> OrderResponse:
        params = {
            "symbol": order_req.symbol,
            "side": order_req.side.value,
            "type": order_req.order_type.value,
            "quantity": str(order_req.quantity),
            "timeInForce": order_req.time_in_force.value,
            "isMarginOrder": "true",
        }

        if order_req.price:
            params["price"] = str(order_req.price)
        if order_req.stop_price:
            params["stopPrice"] = str(order_req.stop_price)
        if order_req.client_order_id:
            params["newClientOrderId"] = order_req.client_order_id

        result = await self.http.post("/sapi/v1/margin/order", params=params, signed=True)

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

        result = await self.http.delete("/sapi/v1/margin/order", params=params, signed=True)

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

        result = await self.http.get("/sapi/v1/margin/order", params=params, signed=True)

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

        results = await self.http.get("/sapi/v1/margin/openOrders", params=params, signed=True)

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

    async def borrow(self, asset: str, amount: Decimal) -> dict:
        params = {
            "asset": asset,
            "amount": str(amount),
        }
        result = await self.http.post("/sapi/v1/margin/loan", params=params, signed=True)
        return result

    async def repay(self, asset: str, amount: Decimal) -> dict:
        params = {
            "asset": asset,
            "amount": str(amount),
        }
        result = await self.http.post("/sapi/v1/margin/repay", params=params, signed=True)
        return result

    async def get_isolated_margin_account(self) -> dict:
        result = await self.http.get("/sapi/v1/margin/isolated/account", signed=True)
        return result

    async def transfer_to_margin(self, asset: str, amount: Decimal) -> dict:
        params = {
            "asset": asset,
            "amount": str(amount),
            "type": "IN",
        }
        result = await self.http.post("/sapi/v1/margin/transfer", params=params, signed=True)
        return result

    async def transfer_from_margin(self, asset: str, amount: Decimal) -> dict:
        params = {
            "asset": asset,
            "amount": str(amount),
            "type": "OUT",
        }
        result = await self.http.post("/sapi/v1/margin/transfer", params=params, signed=True)
        return result
