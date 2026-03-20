"""Paper trading session manager for Binance Futures simulation.

Supports multiple concurrent leveraged sessions with margin tracking,
unrealized P&L, liquidation detection, and full trade history.
"""
from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PaperFuturesPosition:
    symbol: str
    side: str          # "LONG" | "SHORT"
    quantity: Decimal
    entry_price: Decimal
    leverage: int
    margin_used: Decimal
    stop_loss: Optional[Decimal]
    take_profit: Optional[Decimal]
    opened_at: datetime
    trade_id: str

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        if self.side == "LONG":
            raw = (current_price - self.entry_price) * self.quantity
        else:
            raw = (self.entry_price - current_price) * self.quantity
        return raw

    def roi_pct(self, current_price: Decimal) -> Decimal:
        pnl = self.unrealized_pnl(current_price)
        return (pnl / self.margin_used * Decimal("100")) if self.margin_used > 0 else Decimal("0")

    def is_liquidated(self, current_price: Decimal) -> bool:
        """Returns True when unrealized loss wipes the margin."""
        return self.unrealized_pnl(current_price) <= -self.margin_used


@dataclass
class PaperTrade:
    trade_id: str
    symbol: str
    side: str
    entry_price: Decimal
    exit_price: Optional[Decimal]
    quantity: Decimal
    leverage: int
    pnl: Decimal
    pnl_pct: Decimal
    opened_at: datetime
    closed_at: Optional[datetime]
    status: str          # "OPEN" | "CLOSED"
    close_reason: str    # "MANUAL" | "SIGNAL" | "SL" | "TP" | "LIQUIDATION"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class PaperTradingSession:
    def __init__(
        self,
        session_id: str,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        initial_balance: Decimal,
        leverage: int = 1,
    ) -> None:
        self.session_id = session_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.strategy_name = strategy_name
        self.initial_balance = initial_balance
        self.leverage = max(1, min(leverage, 125))
        self.balance = initial_balance          # free USDT (not tied up as margin)
        self.positions: Dict[str, PaperFuturesPosition] = {}
        self.trade_history: List[PaperTrade] = []
        self.started_at = datetime.utcnow()
        self.is_active = True
        self._commission_rate = Decimal("0.0004")  # 0.04 % taker

    # ------------------------------------------------------------------
    # Core trading operations
    # ------------------------------------------------------------------

    def open_position(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> dict:
        side = side.upper()
        if side not in ("LONG", "BUY", "SHORT", "SELL"):
            return {"success": False, "error": f"Invalid side: {side}"}
        # Normalise direction
        direction = "LONG" if side in ("LONG", "BUY") else "SHORT"

        if symbol in self.positions:
            return {"success": False, "error": f"Position already open for {symbol}"}

        notional = quantity * price
        margin_required = notional / self.leverage
        commission = notional * self._commission_rate

        if margin_required + commission > self.balance:
            return {
                "success": False,
                "error": (
                    f"Insufficient balance. Required: {margin_required + commission:.4f} "
                    f"USDT, Available: {self.balance:.4f} USDT"
                ),
            }

        trade_id = str(uuid.uuid4())[:12]
        self.balance -= margin_required + commission

        pos = PaperFuturesPosition(
            symbol=symbol,
            side=direction,
            quantity=quantity,
            entry_price=price,
            leverage=self.leverage,
            margin_used=margin_required,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=datetime.utcnow(),
            trade_id=trade_id,
        )
        self.positions[symbol] = pos

        trade = PaperTrade(
            trade_id=trade_id,
            symbol=symbol,
            side=direction,
            entry_price=price,
            exit_price=None,
            quantity=quantity,
            leverage=self.leverage,
            pnl=Decimal("0"),
            pnl_pct=Decimal("0"),
            opened_at=datetime.utcnow(),
            closed_at=None,
            status="OPEN",
            close_reason="",
        )
        self.trade_history.append(trade)

        logger.info(
            "Paper position opened: %s %s %s @ %s (lev=%dx)",
            session_id_tag(self.session_id), direction, symbol, price, self.leverage,
        )

        return {
            "success": True,
            "trade_id": trade_id,
            "symbol": symbol,
            "side": direction,
            "quantity": str(quantity),
            "entry_price": str(price),
            "margin_used": str(round(margin_required, 4)),
            "leverage": self.leverage,
            "commission": str(round(commission, 6)),
        }

    def close_position(
        self,
        symbol: str,
        price: Decimal,
        reason: str = "MANUAL",
    ) -> dict:
        if symbol not in self.positions:
            return {"success": False, "error": f"No open position for {symbol}"}

        pos = self.positions[symbol]
        pnl = pos.unrealized_pnl(price)
        pnl_pct = pos.roi_pct(price)
        commission = pos.quantity * price * self._commission_rate

        net_pnl = pnl - commission
        # Return margin + net P&L
        self.balance += pos.margin_used + net_pnl

        # Update trade record
        for trade in reversed(self.trade_history):
            if trade.trade_id == pos.trade_id:
                trade.exit_price = price
                trade.pnl = round(net_pnl, 6)
                trade.pnl_pct = round(pnl_pct, 4)
                trade.closed_at = datetime.utcnow()
                trade.status = "CLOSED"
                trade.close_reason = reason
                break

        del self.positions[symbol]

        logger.info(
            "Paper position closed: %s %s @ %s | PnL: %s USDT | Reason: %s",
            session_id_tag(self.session_id), symbol, price, round(net_pnl, 4), reason,
        )

        return {
            "success": True,
            "symbol": symbol,
            "exit_price": str(price),
            "pnl": str(round(net_pnl, 4)),
            "pnl_pct": str(round(pnl_pct, 4)),
            "close_reason": reason,
            "balance_after": str(round(self.balance, 4)),
        }

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_positions_dict(
        self, current_prices: Optional[Dict[str, Decimal]] = None
    ) -> List[dict]:
        out = []
        for sym, pos in self.positions.items():
            cp = (current_prices or {}).get(sym, pos.entry_price)
            upnl = pos.unrealized_pnl(cp)
            roi = pos.roi_pct(cp)
            out.append(
                {
                    "symbol": sym,
                    "side": pos.side,
                    "quantity": str(pos.quantity),
                    "entry_price": str(pos.entry_price),
                    "current_price": str(cp),
                    "leverage": pos.leverage,
                    "margin_used": str(pos.margin_used),
                    "unrealized_pnl": str(round(upnl, 4)),
                    "roi_pct": str(round(roi, 4)),
                    "stop_loss": str(pos.stop_loss) if pos.stop_loss else None,
                    "take_profit": str(pos.take_profit) if pos.take_profit else None,
                    "opened_at": pos.opened_at.isoformat(),
                    "is_liquidated": pos.is_liquidated(cp),
                }
            )
        return out

    def get_balance_info(self) -> dict:
        closed_trades = [t for t in self.trade_history if t.status == "CLOSED"]
        realized_pnl = sum(t.pnl for t in closed_trades)
        total_margin = sum(p.margin_used for p in self.positions.values())
        unrealized_pnl = sum(
            p.unrealized_pnl(p.entry_price) for p in self.positions.values()
        )
        equity = self.balance + total_margin + unrealized_pnl
        ret_pct = (
            (equity - self.initial_balance) / self.initial_balance * 100
            if self.initial_balance > 0
            else Decimal("0")
        )
        return {
            "session_id": self.session_id,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "leverage": self.leverage,
            "initial_balance": str(self.initial_balance),
            "available_balance": str(round(self.balance, 4)),
            "total_margin_used": str(round(total_margin, 4)),
            "unrealized_pnl": str(round(unrealized_pnl, 4)),
            "realized_pnl": str(round(realized_pnl, 4)),
            "equity": str(round(equity, 4)),
            "return_pct": str(round(ret_pct, 4)),
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
            "winning_trades": sum(1 for t in closed_trades if t.pnl > 0),
            "losing_trades": sum(1 for t in closed_trades if t.pnl <= 0),
            "started_at": self.started_at.isoformat(),
            "is_active": self.is_active,
        }

    def get_trade_history(self) -> List[dict]:
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "side": t.side,
                "entry_price": str(t.entry_price),
                "exit_price": str(t.exit_price) if t.exit_price else None,
                "quantity": str(t.quantity),
                "leverage": t.leverage,
                "pnl": str(round(t.pnl, 4)),
                "pnl_pct": str(round(t.pnl_pct, 4)),
                "status": t.status,
                "close_reason": t.close_reason,
                "opened_at": t.opened_at.isoformat(),
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in self.trade_history
        ]

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    def reset(self) -> dict:
        self.balance = self.initial_balance
        self.positions.clear()
        self.trade_history.clear()
        return {
            "success": True,
            "message": "Paper account reset to initial state",
            "balance": str(self.initial_balance),
            "session_id": self.session_id,
        }

    def stop(self) -> None:
        self.is_active = False
        logger.info("Paper trading session stopped: %s", self.session_id)


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class PaperSessionManager:
    """Registry of all active paper trading sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, PaperTradingSession] = {}

    def create_session(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        initial_balance: Decimal,
        leverage: int = 1,
    ) -> PaperTradingSession:
        session_id = str(uuid.uuid4())[:12]
        session = PaperTradingSession(
            session_id=session_id,
            symbol=symbol,
            timeframe=timeframe,
            strategy_name=strategy_name,
            initial_balance=initial_balance,
            leverage=leverage,
        )
        self._sessions[session_id] = session
        logger.info(
            "Paper session created: %s | %s | %s | balance=%s lev=%dx",
            session_id, strategy_name, symbol, initial_balance, leverage,
        )
        return session

    def get(self, session_id: str) -> Optional[PaperTradingSession]:
        return self._sessions.get(session_id)

    def stop(self, session_id: str) -> bool:
        s = self._sessions.get(session_id)
        if s:
            s.stop()
            return True
        return False

    def list_sessions(self) -> List[dict]:
        return [
            {
                "session_id": s.session_id,
                "symbol": s.symbol,
                "timeframe": s.timeframe,
                "strategy_name": s.strategy_name,
                "leverage": s.leverage,
                "initial_balance": str(s.initial_balance),
                "is_active": s.is_active,
                "open_positions": len(s.positions),
                "total_trades": len(s.trade_history),
                "started_at": s.started_at.isoformat(),
            }
            for s in self._sessions.values()
        ]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def session_id_tag(sid: str) -> str:
    return f"[{sid[:8]}]"
