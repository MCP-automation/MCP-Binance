import pytest
from datetime import datetime
from decimal import Decimal

from mcp_app.conversation.flow import ConversationManager, ConversationState, StrategySetupFlow, BacktestSetupFlow


class TestConversationManager:
    def test_create_context(self):
        manager = ConversationManager()
        context = manager.get_or_create_context("session_1")
        
        assert context.session_id == "session_1"
        assert context.state == ConversationState.IDLE

    def test_idle_state_strategy_request(self):
        manager = ConversationManager()
        result = manager.process_user_input("session_1", "I want to set up a strategy")
        
        assert "setup your trading strategy" in result["response"]
        assert result["next_action"] == "await_strategy_input"


class TestStrategySetupFlow:
    def test_get_first_question(self):
        flow = StrategySetupFlow()
        manager = ConversationManager()
        context = manager.get_or_create_context("test")
        
        question = flow.get_next_question(context)
        assert "strategy name" in question.lower()

    def test_validate_strategy_name(self):
        flow = StrategySetupFlow()
        manager = ConversationManager()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "strategy_name", "MyStrategy")
        assert is_valid
        assert context.strategy_config["strategy_name"] == "MyStrategy"

    def test_validate_timeframe(self):
        flow = StrategySetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "timeframe", "1h")
        assert is_valid
        assert context.strategy_config["timeframe"] == "1h"

    def test_invalid_timeframe(self):
        flow = StrategySetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "timeframe", "invalid")
        assert not is_valid

    def test_validate_symbols(self):
        flow = StrategySetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "symbols", "BTCUSDT, ETHUSDT")
        assert is_valid
        assert "BTCUSDT" in context.strategy_config["symbols"]


class TestBacktestSetupFlow:
    def test_get_first_question(self):
        manager = ConversationManager()
        flow = BacktestSetupFlow()
        context = manager.get_or_create_context("test")
        
        question = flow.get_next_question(context)
        assert "start" in question.lower()

    def test_validate_start_date(self):
        manager = ConversationManager()
        flow = BacktestSetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "start_date", "2023-01-01")
        assert is_valid
        assert context.backtest_config["start_date"] == "2023-01-01"

    def test_invalid_date_format(self):
        manager = ConversationManager()
        flow = BacktestSetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "start_date", "invalid")
        assert not is_valid

    def test_validate_capital(self):
        manager = ConversationManager()
        flow = BacktestSetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "initial_capital", "10000")
        assert is_valid
        assert context.backtest_config["initial_capital"] == "10000"

    def test_invalid_capital(self):
        manager = ConversationManager()
        flow = BacktestSetupFlow()
        context = manager.get_or_create_context("test")
        
        is_valid, msg = flow.validate_and_store(context, "initial_capital", "-100")
        assert not is_valid


class TestConversationFlow:
    def test_strategy_setup_flow(self):
        manager = ConversationManager()
        
        result1 = manager.process_user_input("session_1", "setup strategy")
        assert "strategy name" in result1["response"].lower()
        
        result2 = manager.process_user_input("session_1", "MyStrategy")
        assert "timeframe" in result2["response"].lower()
        
        result3 = manager.process_user_input("session_1", "1h")
        assert "symbols" in result3["response"].lower()

    def test_backtest_flow(self):
        manager = ConversationManager()
        
        result1 = manager.process_user_input("session_1", "run backtest")
        assert "start" in result1["response"].lower()
        
        result2 = manager.process_user_input("session_1", "2023-01-01")
        assert "end" in result2["response"].lower()

    def test_status_request(self):
        manager = ConversationManager()
        
        result = manager.process_user_input("session_1", "what's my status")
        assert result["next_action"] == "get_risk_metrics"

    def test_multiple_sessions(self):
        manager = ConversationManager()
        
        result1 = manager.process_user_input("session_1", "setup strategy")
        result2 = manager.process_user_input("session_2", "run backtest")
        
        assert "strategy" in result1["response"].lower()
        assert "backtest" in result2["response"].lower()


class TestMCPServerRunner:
    @pytest.mark.asyncio
    async def test_runner_initialization(self):
        from mcp_app.server.runner import MCPServerRunner
        
        class MockContext:
            exchange_manager = None
            risk_manager = None
            backtest_runner = None
        
        runner = MCPServerRunner(MockContext())
        assert runner._ctx is not None


class TestConversationStateTransitions:
    def test_state_transitions(self):
        manager = ConversationManager()
        
        context = manager.get_or_create_context("session_1")
        assert context.state == ConversationState.IDLE
        
        manager.process_user_input("session_1", "setup strategy")
        assert context.state == ConversationState.STRATEGY_SETUP

    def test_return_to_idle(self):
        manager = ConversationManager()
        
        manager.process_user_input("session_1", "setup strategy")
        context = manager.get_or_create_context("session_1")
        assert context.state == ConversationState.STRATEGY_SETUP
        
        manager.process_user_input("session_1", "cancel")
        assert context.state == ConversationState.STRATEGY_SETUP


class TestMCPProtocol:
    def test_resources_schema(self):
        from mcp_app.protocol import MCPResourcesHandler
        
        resources = MCPResourcesHandler.get_resources()
        
        assert "tools" in resources
        assert len(resources["tools"]) >= 6
        
        tool_names = [t["name"] for t in resources["tools"]]
        assert "place_market_order" in tool_names
        assert "get_positions" in tool_names
        assert "run_backtest" in tool_names
