from __future__ import annotations
import logging
import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from exchange.types import (
    MarketType,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    Position,
    Ticker,
)

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    symbol: str
    market_type: MarketType
    side: OrderSide
    quantity: Decimal
    entry_price: Decimal
    created_at: datetime
    updated_at: datetime
    metadata: dict = field(default_factory=dict)

    @property
    def current_value(self) -> Decimal:
        return self.quantity * self.entry_price

    @property
    def unrealized_pnl(self) -> Decimal:
        return (self.current_value) if self.side == OrderSide.BUY else (-self.current_value)

    def update_mark_price(self, mark_price: Decimal) -> Decimal:
        if self.side == OrderSide.BUY:
            pnl = (mark_price - self.entry_price) * self.quantity
        else:
            pnl = (self.entry_price - mark_price) * self.quantity
        return pnl


@dataclass
class PaperOrder:
    order_id: str
    client_order_id: Optional[str]
    symbol: str
    market_type: MarketType
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal]
    stop_price: Optional[Decimal]
    status: OrderStatus
    filled_quantity: Decimal
    created_at: datetime
    updated_at: datetime
    metadata: dict = field(default_factory=dict)

    def to_response(self) -> OrderResponse:
        return OrderResponse(
            order_id=self.order_id,
            client_order_id=self.client_order_id,
            symbol=self.symbol,
            side=self.side,
            order_type=self.order_type,
            status=self.status,
            quantity=self.quantity,
            price=self.price,
            stop_price=self.stop_price,
            filled_quantity=self.filled_quantity,
            filled_quote_quantity=self.filled_quantity * (self.price or Decimal("0")),
            created_at=self.created_at,
            updated_at=self.updated_at,
            fees=Decimal("0"),
            metadata=self.metadata,
        )


class PaperTradingEngine:
    def __init__(self, initial_balance: Decimal = Decimal("10000")):
        self.initial_balance = initial_balance
        self.balances: Dict[str, Decimal] = {
            "USDT": initial_balance,
        }
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: Dict[str, PaperOrder] = {}
        self.order_history: List[PaperOrder] = []
        self.total_fees = Decimal("0")
        self.created_at = datetime.utcnow()

    def get_balance(self, asset: str = "USDT") -> Decimal:
        return self.balances.get(asset, Decimal("0"))

    def get_total_wallet_balance(self, ticker_prices: Dict[str, Decimal]) -> Decimal:
        total = self.balances.get("USDT", Decimal("0"))
        for asset, quantity in self.balances.items():
            if asset != "USDT":
                price = ticker_prices.get(asset, Decimal("0"))
                total += quantity * price
        return total

    def get_positions(self) -> List[PaperPosition]:
        return list(self.positions.values())

    def place_order(
        self,
        order_req: OrderRequest,
        current_price: Decimal,
    ) -> OrderResponse:
        order_id = str(uuid.uuid4())
        now = datetime.utcnow()

        paper_order = PaperOrder(
            order_id=order_id,
            client_order_id=order_req.client_order_id,
            symbol=order_req.symbol,
            market_type=MarketType.SPOT,
            side=order_req.side,
            order_type=order_req.order_type,
            quantity=order_req.quantity,
            price=order_req.price or current_price,
            stop_price=order_req.stop_price,
            status=OrderStatus.NEW,
            filled_quantity=Decimal("0"),
            created_at=now,
            updated_at=now,
            metadata=order_req.metadata,
        )

        if order_req.order_type == OrderType.MARKET:
            paper_order.status = OrderStatus.FILLED
            paper_order.filled_quantity = order_req.quantity
            paper_order.price = current_price
            paper_order.updated_at = now

            fee = order_req.quantity * current_price * Decimal("0.001")
            self.total_fees += fee

            if order_req.side == OrderSide.BUY:
                cost = order_req.quantity * current_price + fee
                if self.balances.get("USDT", Decimal("0")) < cost:
                    paper_order.status = OrderStatus.REJECTED
                    paper_order.updated_at = now
                    self.orders[order_id] = paper_order
                    return paper_order.to_response()

                self.balances["USDT"] = self.balances.get("USDT", Decimal("0")) - cost

                pos_key = f"{order_req.symbol}_BUY"
                if pos_key in self.positions:
                    pos = self.positions[pos_key]
                    avg_price = (
                        (pos.quantity * pos.entry_price + order_req.quantity * current_price)
                        / (pos.quantity + order_req.quantity)
                    )
                    pos.quantity += order_req.quantity
                    pos.entry_price = avg_price
                    pos.updated_at = now
                else:
                    self.positions[pos_key] = PaperPosition(
                        symbol=order_req.symbol,
                        market_type=MarketType.SPOT,
                        side=OrderSide.BUY,
                        quantity=order_req.quantity,
                        entry_price=current_price,
                        created_at=now,
                        updated_at=now,
                    )

            elif order_req.side == OrderSide.SELL:
                revenue = order_req.quantity * current_price - fee
                self.balances["USDT"] = self.balances.get("USDT", Decimal("0")) + revenue

        self.orders[order_id] = paper_order
        self.order_history.append(paper_order)
        return paper_order.to_response()

    def cancel_order(self, order_id: str) -> OrderResponse:
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")

        paper_order = self.orders[order_id]

        if paper_order.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            return paper_order.to_response()

        paper_order.status = OrderStatus.CANCELED
        paper_order.updated_at = datetime.utcnow()

        if paper_order.filled_quantity > 0:
            paper_order.status = OrderStatus.PARTIALLY_FILLED

        return paper_order.to_response()

    def get_order(self, order_id: str) -> OrderResponse:
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found")
        return self.orders[order_id].to_response()

    def update_position_mark_price(
        self,
        symbol: str,
        side: OrderSide,
        mark_price: Decimal,
    ) -> Optional[Decimal]:
        pos_key = f"{symbol}_{side.value}"
        if pos_key not in self.positions:
            return None

        position = self.positions[pos_key]
        return position.update_mark_price(mark_price)

    def get_total_pnl(self, ticker_prices: Dict[str, Decimal]) -> Decimal:
        total_pnl = Decimal("0")
        for position in self.positions.values():
            if position.symbol in ticker_prices:
                pnl = position.update_mark_price(ticker_prices[position.symbol])
                total_pnl += pnl
        return total_pnl - self.total_fees

    def get_stats(self) -> dict:
        total_wallet = sum(self.balances.values())
        total_pnl = self.get_total_pnl({})

        return {
            "initial_balance": float(self.initial_balance),
            "current_balance": float(self.balances.get("USDT", Decimal("0"))),
            "total_wallet_balance": float(total_wallet),
            "total_pnl": float(total_pnl),
            "total_fees": float(self.total_fees),
            "total_orders": len(self.order_history),
            "open_positions": len([p for p in self.positions.values()]),
            "created_at": self.created_at.isoformat(),
        }
