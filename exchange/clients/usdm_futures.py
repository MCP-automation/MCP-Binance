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
    Position,
    Ticker,
    OHLCV,
    PositionMode,
)
from exchange.http_client import UnifiedHTTPClient

logger = logging.getLogger(__name__)


class USDMFuturesClient:
    def __init__(self, http_client: UnifiedHTTPClient):
        self.http = http_client
        self.market_type = MarketType.USDM_FUTURES

    async def get_account_info(self) -> AccountInfo:
        result = await self.http.get("/fapi/v3/account", signed=True)

        balances = [
            AccountBalance(
                asset=b["asset"],
                total=Decimal(b["walletBalance"]),
                available=Decimal(b["availableBalance"]),
                on_order=Decimal(b["walletBalance"]) - Decimal(b["availableBalance"]),
            )
            for b in result.get("assets", [])
            if Decimal(b["walletBalance"]) > 0
        ]

        total_wallet_balance = Decimal(result.get("totalWalletBalance", 0))
        total_unrealized_pnl = Decimal(result.get("totalUnrealizedProfit", 0))

        return AccountInfo(
            market_type=self.market_type,
            balances=balances,
            total_wallet_balance=total_wallet_balance,
            total_unrealized_pnl=total_unrealized_pnl,
            total_cross_margin_balance=Decimal(result.get("totalCrossWalletBalance", 0)),
            can_trade=result.get("canTrade", True),
            can_withdraw=result.get("canWithdraw", True),
            can_deposit=result.get("canDeposit", True),
            position_mode=PositionMode(result.get("positionMode", "ONE_WAY").upper()),
            updated_at=datetime.utcnow(),
        )

    async def get_exchange_info(self) -> dict:
        result = await self.http.get("/fapi/v1/exchangeInfo")
        return result

    async def get_ticker(self, symbol: str) -> Ticker:
        result = await self.http.get("/fapi/v1/ticker/24hr", params={"symbol": symbol})

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
            "limit": min(limit, 1500),
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        klines = await self.http.get("/fapi/v1/klines", params=params)

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

    async def get_positions(self) -> list[Position]:
        result = await self.http.get("/fapi/v3/account", signed=True)

        positions = []
        for pos in result.get("positions", []):
            if Decimal(pos["positionAmt"]) == 0:
                continue

            quantity = Decimal(pos["positionAmt"])
            entry_price = Decimal(pos.get("entryPrice", 0))
            mark_price = Decimal(pos.get("markPrice", 0))

            unrealized_pnl = Decimal(pos.get("unRealizedProfit", 0))
            unrealized_pnl_pct = (
                (unrealized_pnl / (entry_price * abs(quantity)) * Decimal("100"))
                if entry_price > 0
                else Decimal("0")
            )

            positions.append(
                Position(
                    symbol=pos["symbol"],
                    market_type=self.market_type,
                    side=OrderSide.BUY if quantity > 0 else OrderSide.SELL,
                    quantity=abs(quantity),
                    entry_price=entry_price,
                    current_price=mark_price,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    maintenance_margin=Decimal(pos.get("maintMargin", 0)),
                    position_side=pos.get("positionSide", "BOTH"),
                    leverage=Decimal(pos.get("leverage", 1)),
                    mark_price=mark_price,
                    funding_rate=Decimal(pos.get("fundingRate", 0)),
                    next_funding_time=datetime.fromtimestamp(
                        int(pos.get("nextFundingTime", 0)) / 1000
                    )
                    if pos.get("nextFundingTime")
                    else None,
                )
            )
        return positions

    async def place_order(
        self,
        order_req: OrderRequest,
        position_side: Literal["LONG", "SHORT"] = "LONG",
    ) -> OrderResponse:
        params = {
            "symbol": order_req.symbol,
            "side": order_req.side.value,
            "type": order_req.order_type.value,
            "quantity": str(order_req.quantity),
            "positionSide": position_side,
            "timeInForce": order_req.time_in_force.value,
        }

        if order_req.price:
            params["price"] = str(order_req.price)
        if order_req.stop_price:
            params["stopPrice"] = str(order_req.stop_price)
        if order_req.reduce_only:
            params["reduceOnly"] = "true"
        if order_req.client_order_id:
            params["newClientOrderId"] = order_req.client_order_id

        result = await self.http.post("/fapi/v1/order", params=params, signed=True)

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
            filled_quote_quantity=Decimal(result.get("cumQuote", 0)),
            created_at=datetime.fromtimestamp(result["time"] / 1000),
            updated_at=datetime.fromtimestamp(result["updateTime"] / 1000),
            position_side=result.get("positionSide", "BOTH"),
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

        result = await self.http.delete("/fapi/v1/order", params=params, signed=True)

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
            filled_quote_quantity=Decimal(result.get("cumQuote", 0)),
            created_at=datetime.fromtimestamp(result["time"] / 1000),
            updated_at=datetime.fromtimestamp(result["updateTime"] / 1000),
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

        result = await self.http.get("/fapi/v1/order", params=params, signed=True)

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
            filled_quote_quantity=Decimal(result.get("cumQuote", 0)),
            created_at=datetime.fromtimestamp(result["time"] / 1000),
            updated_at=datetime.fromtimestamp(result["updateTime"] / 1000),
            fees=Decimal("0"),
        )

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[OrderResponse]:
        params = {}
        if symbol:
            params["symbol"] = symbol

        results = await self.http.get("/fapi/v1/openOrders", params=params, signed=True)

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
                    filled_quote_quantity=Decimal(result.get("cumQuote", 0)),
                    created_at=datetime.fromtimestamp(result["time"] / 1000),
                    updated_at=datetime.fromtimestamp(result["updateTime"] / 1000),
                    fees=Decimal("0"),
                )
            )
        return orders

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        params = {
            "symbol": symbol,
            "leverage": leverage,
        }
        result = await self.http.post("/fapi/v1/leverage", params=params, signed=True)
        return result

    async def set_margin_type(self, symbol: str, margin_type: Literal["ISOLATED", "CROSSED"]) -> dict:
        params = {
            "symbol": symbol,
            "marginType": margin_type,
        }
        result = await self.http.post("/fapi/v1/marginType", params=params, signed=True)
        return result

    async def change_position_mode(self, dual_side_position: bool) -> dict:
        params = {
            "dualSidePosition": "true" if dual_side_position else "false",
        }
        result = await self.http.post("/fapi/v1/positionSide/dual", params=params, signed=True)
        return result
