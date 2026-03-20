from __future__ import annotations
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class ConversationState(Enum):
    IDLE = "IDLE"
    STRATEGY_SETUP = "STRATEGY_SETUP"
    BACKTEST_CONFIG = "BACKTEST_CONFIG"
    TRADING_ACTIVE = "TRADING_ACTIVE"
    MONITORING = "MONITORING"
    ERROR = "ERROR"


@dataclass
class ConversationContext:
    session_id: str
    state: ConversationState
    created_at: datetime
    last_updated: datetime
    strategy_config: Dict[str, Any] = field(default_factory=dict)
    backtest_config: Dict[str, Any] = field(default_factory=dict)
    trading_config: Dict[str, Any] = field(default_factory=dict)
    messages: list = field(default_factory=list)
    error_message: Optional[str] = None


class StrategySetupFlow:
    def __init__(self):
        self.required_fields = [
            "strategy_name",
            "timeframe",
            "symbols",
            "entry_condition",
            "exit_condition",
        ]
        self.optional_fields = [
            "stop_loss_pct",
            "take_profit_pct",
            "position_size_pct",
            "max_positions",
        ]

    def get_next_question(self, context: ConversationContext) -> str:
        for field in self.required_fields:
            if field not in context.strategy_config:
                return self._get_question_for_field(field)

        return "Strategy setup complete! Would you like to backtest this strategy or deploy it live?"

    def _get_question_for_field(self, field: str) -> str:
        questions = {
            "strategy_name": "What is the name of your strategy?",
            "timeframe": "What timeframe will this strategy trade on? (e.g., 1h, 4h, 1d)",
            "symbols": "Which symbols will you trade? (comma-separated, e.g., BTCUSDT,ETHUSDT)",
            "entry_condition": "Define the entry condition using Python-like syntax (e.g., current_close > sma_20)",
            "exit_condition": "Define the exit condition (e.g., current_close < sma_10)",
        }
        return questions.get(field, f"Please provide {field}")

    def validate_and_store(self, context: ConversationContext, field: str, value: str) -> tuple[bool, str]:
        if field == "strategy_name":
            if len(value) < 3:
                return False, "Strategy name must be at least 3 characters"
            context.strategy_config[field] = value
            return True, f"Strategy name set to: {value}"

        elif field == "timeframe":
            valid_timeframes = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
            if value not in valid_timeframes:
                return False, f"Invalid timeframe. Valid options: {', '.join(valid_timeframes)}"
            context.strategy_config[field] = value
            return True, f"Timeframe set to: {value}"

        elif field == "symbols":
            symbols = [s.strip().upper() for s in value.split(",")]
            if not all(s.endswith("USDT") or s.endswith("BUSD") for s in symbols):
                return False, "All symbols should be valid trading pairs (e.g., BTCUSDT)"
            context.strategy_config[field] = symbols
            return True, f"Symbols set to: {', '.join(symbols)}"

        elif field == "entry_condition":
            if len(value) < 5:
                return False, "Entry condition must be more complex"
            context.strategy_config[field] = value
            return True, f"Entry condition: {value}"

        elif field == "exit_condition":
            if len(value) < 5:
                return False, "Exit condition must be more complex"
            context.strategy_config[field] = value
            return True, f"Exit condition: {value}"

        return False, f"Unknown field: {field}"


class BacktestSetupFlow:
    def __init__(self):
        self.required_fields = [
            "start_date",
            "end_date",
            "initial_capital",
        ]
        self.optional_fields = [
            "stop_loss_pct",
            "take_profit_pct",
            "commission_pct",
            "slippage_pct",
        ]

    def get_next_question(self, context: ConversationContext) -> str:
        for field in self.required_fields:
            if field not in context.backtest_config:
                return self._get_question_for_field(field)

        return "Backtest configuration complete. Ready to run backtest?"

    def _get_question_for_field(self, field: str) -> str:
        questions = {
            "start_date": "When should the backtest start? (YYYY-MM-DD format)",
            "end_date": "When should the backtest end? (YYYY-MM-DD format)",
            "initial_capital": "What is the initial capital for backtesting? (e.g., 10000)",
        }
        return questions.get(field, f"Please provide {field}")

    def validate_and_store(self, context: ConversationContext, field: str, value: str) -> tuple[bool, str]:
        if field == "start_date":
            try:
                from datetime import datetime
                datetime.fromisoformat(value)
                context.backtest_config[field] = value
                return True, f"Start date set to: {value}"
            except ValueError:
                return False, "Invalid date format. Use YYYY-MM-DD"

        elif field == "end_date":
            try:
                from datetime import datetime
                datetime.fromisoformat(value)
                if "start_date" in context.backtest_config:
                    if value <= context.backtest_config["start_date"]:
                        return False, "End date must be after start date"
                context.backtest_config[field] = value
                return True, f"End date set to: {value}"
            except ValueError:
                return False, "Invalid date format. Use YYYY-MM-DD"

        elif field == "initial_capital":
            try:
                capital = float(value)
                if capital <= 0:
                    return False, "Capital must be positive"
                context.backtest_config[field] = str(capital)
                return True, f"Initial capital set to: ${capital:,.2f}"
            except ValueError:
                return False, "Invalid capital amount"

        return False, f"Unknown field: {field}"


class ConversationManager:
    def __init__(self):
        self.contexts: Dict[str, ConversationContext] = {}
        self.strategy_flow = StrategySetupFlow()
        self.backtest_flow = BacktestSetupFlow()

    def get_or_create_context(self, session_id: str) -> ConversationContext:
        if session_id not in self.contexts:
            self.contexts[session_id] = ConversationContext(
                session_id=session_id,
                state=ConversationState.IDLE,
                created_at=datetime.utcnow(),
                last_updated=datetime.utcnow(),
            )
        return self.contexts[session_id]

    def process_user_input(self, session_id: str, user_input: str) -> dict:
        context = self.get_or_create_context(session_id)

        if context.state == ConversationState.IDLE:
            return self._handle_idle_state(context, user_input)
        elif context.state == ConversationState.STRATEGY_SETUP:
            return self._handle_strategy_setup(context, user_input)
        elif context.state == ConversationState.BACKTEST_CONFIG:
            return self._handle_backtest_config(context, user_input)
        elif context.state == ConversationState.TRADING_ACTIVE:
            return self._handle_trading_active(context, user_input)
        elif context.state == ConversationState.MONITORING:
            return self._handle_monitoring(context, user_input)

        return {
            "response": "An error occurred. Please try again.",
            "context_state": context.state.value,
            "next_action": None,
        }

    def _handle_idle_state(self, context: ConversationContext, user_input: str) -> dict:
        lower_input = user_input.lower()

        if "strategy" in lower_input or "setup" in lower_input:
            context.state = ConversationState.STRATEGY_SETUP
            next_q = self.strategy_flow.get_next_question(context)
            return {
                "response": f"Let's set up your trading strategy. {next_q}",
                "context_state": context.state.value,
                "next_action": "await_strategy_input",
            }

        elif "backtest" in lower_input:
            context.state = ConversationState.BACKTEST_CONFIG
            next_q = self.backtest_flow.get_next_question(context)
            return {
                "response": f"Let's configure a backtest. {next_q}",
                "context_state": context.state.value,
                "next_action": "await_backtest_input",
            }

        elif "status" in lower_input or "metrics" in lower_input:
            return {
                "response": "Fetching current risk metrics...",
                "context_state": context.state.value,
                "next_action": "get_risk_metrics",
            }

        else:
            return {
                "response": "I can help you with: setup strategy, run backtest, check status, or place trades. What would you like to do?",
                "context_state": context.state.value,
                "next_action": None,
            }

    def _handle_strategy_setup(self, context: ConversationContext, user_input: str) -> dict:
        if "done" in user_input.lower() or "complete" in user_input.lower():
            if all(f in context.strategy_config for f in self.strategy_flow.required_fields):
                context.state = ConversationState.IDLE
                return {
                    "response": "Strategy setup complete! Would you like to backtest it or deploy it live?",
                    "strategy_config": context.strategy_config,
                    "context_state": context.state.value,
                    "next_action": None,
                }
            else:
                missing = [f for f in self.strategy_flow.required_fields if f not in context.strategy_config]
                return {
                    "response": f"Strategy setup incomplete. Missing: {', '.join(missing)}",
                    "context_state": ConversationState.STRATEGY_SETUP.value,
                    "next_action": None,
                }

        next_field = None
        for field in self.strategy_flow.required_fields:
            if field not in context.strategy_config:
                next_field = field
                break

        if next_field:
            is_valid, msg = self.strategy_flow.validate_and_store(context, next_field, user_input)
            if not is_valid:
                return {
                    "response": f"Invalid input: {msg}. Please try again.",
                    "context_state": context.state.value,
                    "next_action": None,
                }

            next_q = self.strategy_flow.get_next_question(context)
            return {
                "response": f"{msg}\n\n{next_q}",
                "context_state": context.state.value,
                "next_action": "await_strategy_input",
            }

        return {
            "response": "Strategy setup complete!",
            "strategy_config": context.strategy_config,
            "context_state": context.state.value,
            "next_action": None,
        }

    def _handle_backtest_config(self, context: ConversationContext, user_input: str) -> dict:
        if "cancel" in user_input.lower():
            context.state = ConversationState.IDLE
            return {
                "response": "Backtest setup cancelled. How else can I help?",
                "context_state": context.state.value,
                "next_action": None,
            }

        next_field = None
        for field in self.backtest_flow.required_fields:
            if field not in context.backtest_config:
                next_field = field
                break

        if next_field:
            is_valid, msg = self.backtest_flow.validate_and_store(context, next_field, user_input)
            if not is_valid:
                return {
                    "response": f"Invalid input: {msg}. Please try again.",
                    "context_state": context.state.value,
                    "next_action": None,
                }

            next_q = self.backtest_flow.get_next_question(context)
            return {
                "response": f"{msg}\n\n{next_q}",
                "context_state": context.state.value,
                "next_action": "await_backtest_input",
            }

        context.state = ConversationState.IDLE
        return {
            "response": "Backtest configuration complete! Ready to run backtest with these settings.",
            "backtest_config": context.backtest_config,
            "context_state": context.state.value,
            "next_action": "run_backtest",
        }

    def _handle_trading_active(self, context: ConversationContext, user_input: str) -> dict:
        if "close" in user_input.lower() or "stop" in user_input.lower():
            context.state = ConversationState.IDLE
            return {
                "response": "Stopping live trading. All positions will be closed.",
                "context_state": context.state.value,
                "next_action": "close_all_positions",
            }

        return {
            "response": "Live trading active. Type 'close' to stop or 'status' for metrics.",
            "context_state": context.state.value,
            "next_action": None,
        }

    def _handle_monitoring(self, context: ConversationContext, user_input: str) -> dict:
        if "stop" in user_input.lower():
            context.state = ConversationState.IDLE
            return {
                "response": "Monitoring stopped.",
                "context_state": context.state.value,
                "next_action": None,
            }

        return {
            "response": "Currently monitoring positions. Type 'stop' to exit monitoring mode.",
            "context_state": context.state.value,
            "next_action": "get_risk_metrics",
        }
