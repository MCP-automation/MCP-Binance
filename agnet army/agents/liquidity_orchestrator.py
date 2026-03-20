from typing import Dict, Any, Optional
import logging
from datetime import datetime

from exchange.exchange_adapter import ExchangeAdapter
from agents.liquidity_agent import LiquidityAgent


logger = logging.getLogger(__name__)


class LiquidityOrchestrator:
    def __init__(self, exchange: ExchangeAdapter):
        self.exchange = exchange
        self.liquidity_agent = LiquidityAgent(exchange)

    def get_liquidity_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get liquidity analysis for a symbol"""
        try:
            analysis = self.liquidity_agent.get_liquidity(symbol)
            if analysis:
                return {
                    "symbol": analysis.symbol,
                    "current_price": analysis.current_price,
                    "bid_liquidity": [
                        {"price": l.price, "volume": l.volume, "strength": l.strength}
                        for l in analysis.bid_liquidity[:5]  # Top 5 levels
                    ],
                    "ask_liquidity": [
                        {"price": l.price, "volume": l.volume, "strength": l.strength}
                        for l in analysis.ask_liquidity[:5]
                    ],
                    "volume_profile": dict(
                        list(analysis.volume_profile.items())[:10]
                    ),  # Top 10 price levels
                    "high_24h": analysis.high_24h,
                    "low_24h": analysis.low_24h,
                    "vwap_24h": analysis.vwap_24h,
                    "volatility_24h": analysis.volatility_24h,
                    "momentum_24h": analysis.momentum_24h,
                    "timestamp": analysis.timestamp.isoformat(),
                }
        except Exception as e:
            logger.error(f"Failed to get liquidity analysis for {symbol}: {e}")
        return None

    def get_fast_trade_opportunities(self, symbol: str, max_slippage_pct: float = 0.1) -> list:
        """Get fast trade opportunities based on liquidity and 24h levels"""
        try:
            return self.liquidity_agent.get_fast_trade_opportunities(symbol, max_slippage_pct)
        except Exception as e:
            logger.error(f"Failed to get trade opportunities for {symbol}: {e}")
            return []

    def get_status(self) -> Dict[str, Any]:
        """Get orchestrator status"""
        return {
            "exchange_connected": self.exchange.is_connected(),
            "liquidity_agent_status": self.liquidity_agent.get_status(),
        }


# Example usage
if __name__ == "__main__":
    # This is just an example - in practice, you would get API keys from secure storage
    import os
    from exchange.binance_adapter import BinanceAdapter

    # For demonstration, we'll use testnet
    # Replace with your actual API keys or use environment variables
    api_key = os.getenv("BINANCE_API_KEY", "test")
    api_secret = os.getenv("BINANCE_API_SECRET", "test")

    exchange = BinanceAdapter(api_key, api_secret, testnet=True)
    orchestrator = LiquidityOrchestrator(exchange)

    symbol = "BTCUSDT"
    print(f"Getting liquidity analysis for {symbol}...")
    analysis = orchestrator.get_liquidity_analysis(symbol)
    if analysis:
        print(f"Current Price: {analysis['current_price']}")
        print(f"24h High: {analysis['high_24h']}")
        print(f"24h Low: {analysis['low_24h']}")
        print(f"Bid Liquidity (top 5): {analysis['bid_liquidity']}")
        print(f"Ask Liquidity (top 5): {analysis['ask_liquidity']}")

    print("\nGetting fast trade opportunities...")
    opportunities = orchestrator.get_fast_trade_opportunities(symbol)
    for opp in opportunities:
        print(f"Opportunity: {opp['type']} {opp['symbol']} - {opp['reason']}")
        print(f"  Entry: {opp['entry_price']}, Target: {opp['target']}, Stop: {opp['stop_loss']}")
        print(f"  Confidence: {opp['confidence']:.2f}")
