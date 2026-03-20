from typing import Dict, Any, List, Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import defaultdict
import threading
import logging
from weakref import WeakSet


logger = logging.getLogger(__name__)


class EventType(Enum):
    CANDLE = "candle"
    TICKER = "ticker"
    SIGNAL = "signal"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_UPDATED = "position_updated"
    RISK_CHECK = "risk_check"
    RISK_REJECTED = "risk_rejected"
    TRADING_ERROR = "trading_error"
    SYSTEM_ERROR = "system_error"
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    LIQUIDITY_UPDATE = "liquidity_update"
    FAST_TRADE_OPPORTUNITY = "fast_trade_opportunity"


@dataclass
class Event:
    event_type: EventType
    data: Any
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.source:
            self.source = self.event_type.value


EventHandler = Callable[[Event], None]


class EventBus:
    def __init__(self, async_mode: bool = False):
        self._handlers: Dict[EventType, WeakSet[EventHandler]] = defaultdict(WeakSet)
        self._global_handlers: WeakSet[EventHandler] = WeakSet()
        self._lock = threading.RLock()
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._async_mode = async_mode

        if async_mode:
            self._async_queue: List[Event] = []
            self._worker_thread: Optional[threading.Thread] = None

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        with self._lock:
            self._handlers[event_type].add(handler)
            logger.debug(f"Subscribed handler to {event_type.value}")

    def subscribe_all(self, handler: EventHandler) -> None:
        with self._lock:
            self._global_handlers.add(handler)
            logger.debug(f"Subscribed global handler")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        with self._lock:
            if event_type in self._handlers:
                self._handlers[event_type].discard(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        with self._lock:
            self._global_handlers.discard(handler)
            for handlers in self._handlers.values():
                handlers.discard(handler)

    def publish(self, event: Event) -> None:
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

        handlers_to_call = []

        with self._lock:
            handlers_to_call.extend(self._global_handlers)
            if event.event_type in self._handlers:
                handlers_to_call.extend(self._handlers[event.event_type])

        for handler in handlers_to_call:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}", exc_info=True)

    def emit(
        self,
        event_type: EventType,
        data: Any,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = Event(
            event_type=event_type,
            data=data,
            source=source or event_type.value,
            metadata=metadata or {},
        )
        self.publish(event)

    def get_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        with self._lock:
            if event_type:
                return [e for e in self._event_history[-limit:] if e.event_type == event_type]
            return self._event_history[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._event_history.clear()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            stats = {}
            for event_type in EventType:
                count = sum(1 for e in self._event_history if e.event_type == event_type)
                stats[event_type.value] = count
            return {
                "total_events": len(self._event_history),
                "by_type": stats,
                "subscribers": {
                    "global": len(self._global_handlers),
                    **{et.value: len(self._handlers[et]) for et in EventType},
                },
            }


class EventDrivenComponent:
    def __init__(self, event_bus: EventBus, name: str):
        self.event_bus = event_bus
        self.name = name
        self._handlers: List[Callable] = []

    def on(self, event_type: EventType, handler: Callable[[Event], None]) -> None:
        self.event_bus.subscribe(event_type, handler)
        self._handlers.append(handler)

    def emit(
        self, event_type: EventType, data: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        self.event_bus.emit(event_type, data, self.name, metadata)

    def cleanup(self) -> None:
        for handler in self._handlers:
            self.event_bus.unsubscribe_all(handler)
        self._handlers.clear()
