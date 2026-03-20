from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Literal
from decimal import Decimal
from datetime import datetime


class MarketType(Enum):
    SPOT = "SPOT"
    USDM_FUTURES = "USDM_FUTURES"
    COINM_FUTURES = "COINM_FUTURES"
    MARGIN = "MARGIN"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"


class OrderStatus(Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    PENDING_CANCEL = "PENDING_CANCEL"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeInForce(Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"
    PO = "PO"


class PositionMode(Enum):
    ONE_WAY = "ONE_WAY"
    HEDGE = "HEDGE"


class MarginType(Enum):
    CROSSED = "CROSSED"
    ISOLATED = "ISOLATED"


@dataclass
class Ticker:
    symbol: str
    market_type: MarketType
    bid: Decimal
    ask: Decimal
    last: Decimal
    high: Decimal
    low: Decimal
    volume: Decimal
    quote_volume: Decimal
    timestamp: datetime


@dataclass
class OHLCV:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_asset_volume: Optional[Decimal] = None
    number_of_trades: Optional[int] = None
    taker_buy_base_volume: Optional[Decimal] = None
    taker_buy_quote_volume: Optional[Decimal] = None


@dataclass
class OrderRequest:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.GTC
    reduce_only: bool = False
    post_only: bool = False
    client_order_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class OrderResponse:
    order_id: str
    client_order_id: Optional[str]
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    quantity: Decimal
    price: Optional[Decimal]
    stop_price: Optional[Decimal]
    filled_quantity: Decimal
    filled_quote_quantity: Decimal
    created_at: datetime
    updated_at: datetime
    fees: Decimal = Decimal("0")
    fee_asset: Optional[str] = None
    position_side: Optional[Literal["LONG", "SHORT", "BOTH"]] = None
    working_type: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Position:
    symbol: str
    market_type: MarketType
    side: OrderSide
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    maintenance_margin: Optional[Decimal] = None
    margin_level: Optional[Decimal] = None
    isolated_margin_available: Optional[Decimal] = None
    position_side: Optional[Literal["LONG", "SHORT", "BOTH"]] = None
    leverage: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    funding_rate: Optional[Decimal] = None
    next_funding_time: Optional[datetime] = None


@dataclass
class AccountBalance:
    asset: str
    total: Decimal
    available: Decimal
    on_order: Decimal
    borrowed: Optional[Decimal] = None
    free_margin: Optional[Decimal] = None


@dataclass
class AccountInfo:
    market_type: MarketType
    balances: list[AccountBalance]
    total_wallet_balance: Decimal
    total_unrealized_pnl: Decimal
    total_cross_margin_balance: Optional[Decimal] = None
    can_trade: bool = True
    can_withdraw: bool = True
    can_deposit: bool = True
    position_mode: Optional[PositionMode] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExchangeInfo:
    market_type: MarketType
    symbols: list[str]
    timezone: str
    server_time: datetime
    rate_limits: dict = field(default_factory=dict)
    trading_rules: dict = field(default_factory=dict)


@dataclass
class CandleStreamData:
    symbol: str
    market_type: MarketType
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: datetime
    quote_asset_volume: Decimal
    number_of_trades: int
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal
    is_closed: bool
    event_time: datetime


@dataclass
class TradeStreamData:
    symbol: str
    market_type: MarketType
    trade_id: str
    order_id: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    commission: Decimal
    commission_asset: str
    timestamp: datetime
    event_time: datetime


@dataclass
class AggTradeStreamData:
    symbol: str
    market_type: MarketType
    trade_id: str
    price: Decimal
    quantity: Decimal
    first_trade_id: str
    last_trade_id: str
    timestamp: datetime
    is_buyer_maker: bool
    event_time: datetime


@dataclass
class OrderUpdate:
    symbol: str
    market_type: MarketType
    order_id: str
    client_order_id: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    quantity: Decimal
    price: Optional[Decimal]
    stop_price: Optional[Decimal]
    filled_quantity: Decimal
    filled_quote_quantity: Decimal
    commission: Decimal
    commission_asset: str
    transaction_time: datetime
    event_time: datetime
    reject_reason: Optional[str] = None
    position_side: Optional[Literal["LONG", "SHORT", "BOTH"]] = None


@dataclass
class MarkPriceUpdate:
    symbol: str
    market_type: MarketType
    mark_price: Decimal
    index_price: Decimal
    estimated_settlement_price: Decimal
    funding_rate: Decimal
    next_funding_time: datetime
    event_time: datetime


@dataclass
class LiquidationUpdate:
    symbol: str
    market_type: MarketType
    side: OrderSide
    quantity: Decimal
    price: Decimal
    order_id: str
    timestamp: datetime
    event_time: datetime
