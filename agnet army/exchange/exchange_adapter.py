from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


class ExchangeError(Exception):
    def __init__(self, message: str, code: int = -1):
        self.message = message
        self.code = code
        super().__init__(self.message)


class RateLimitError(ExchangeError):
    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, code=-1003)


class InsufficientBalanceError(ExchangeError):
    def __init__(self, message: str = "Insufficient balance"):
        super().__init__(message, code=-1001)


@dataclass
class TickerPrice:
    symbol: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    timestamp: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass
class OrderBook:
    symbol: str
    bids: List[tuple[float, float]]
    asks: List[tuple[float, float]]
    timestamp: datetime


@dataclass
class Position:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    leverage: int
    unrealized_pnl: float
    realized_pnl: float
    notional_value: float
    liquidation_price: Optional[float] = None
    margin_used: float = 0.0
    open_time: Optional[datetime] = None


@dataclass
class AccountBalance:
    asset: str
    free: float
    locked: float
    total: float

    @property
    def available(self) -> float:
        return self.free


@dataclass
class OrderResponse:
    order_id: int
    symbol: str
    side: str
    quantity: float
    price: float
    filled_quantity: float
    avg_fill_price: float
    status: str
    client_order_id: Optional[str] = None


class ExchangeAdapter(ABC):
    @abstractmethod
    def get_ticker(self, symbol: str) -> TickerPrice:
        pass

    @abstractmethod
    def get_24h_ticker(self, symbol: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_balance(self, asset: str = "USDT") -> AccountBalance:
        pass

    @abstractmethod
    def get_all_balances(self) -> List[AccountBalance]:
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Position]:
        pass

    @abstractmethod
    def get_all_positions(self) -> List[Position]:
        pass

    @abstractmethod
    def place_market_order(
        self, symbol: str, side: str, quantity: float, reduce_only: bool = False
    ) -> OrderResponse:
        pass

    @abstractmethod
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> OrderResponse:
        pass

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: int) -> bool:
        pass

    @abstractmethod
    def get_order(self, symbol: str, order_id: int) -> Optional[OrderResponse]:
        pass

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        pass

    @abstractmethod
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[List[Any]]:
        pass

    @abstractmethod
    def get_server_time(self) -> int:
        pass

    def is_connected(self) -> bool:
        return True
