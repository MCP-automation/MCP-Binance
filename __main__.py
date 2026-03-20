"""CLI entry point: python -m binance_mcp [command]

Commands
--------
  tools      List all registered MCP tools (name + description)
  run        Start the MCP stdio server (default when no command given)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the project root (this file's directory) is on sys.path so all
# internal imports resolve correctly whether the user runs:
#   python -m binance_mcp tools          (from parent dir)
#   python __main__.py tools             (from project dir)
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _cmd_tools() -> None:
    from mcp_app.protocol import MCPResourcesHandler

    resources = MCPResourcesHandler.get_resources()
    tools = resources["tools"]

    print(f"\n{'='*60}")
    print(f"  Binance MCP — {len(tools)} registered tools")
    print(f"{'='*60}\n")

    sections = {
        "Core Trading":       ["place_market_order", "get_positions", "close_position",
                               "get_risk_metrics", "run_backtest", "calculate_position_size"],
        "Market Data":        ["get_ticker", "get_order_book", "get_klines",
                               "get_funding_rate", "get_open_interest", "get_recent_trades"],
        "Symbol Discovery":   ["get_futures_symbols"],
        "Futures Backtest":   ["run_futures_backtest", "scan_futures_backtest"],
        "Paper Trading":      ["start_paper_trading", "stop_paper_trading", "get_paper_positions",
                               "get_paper_balance", "get_paper_trade_history", "reset_paper_account"],
        "Live Execution":     ["place_limit_order", "set_leverage", "cancel_order"],
    }

    tool_map = {t["name"]: t for t in tools}

    for section, names in sections.items():
        print(f"  [{section}]")
        for name in names:
            tool = tool_map.get(name)
            if tool:
                desc = tool["description"]
                # Truncate long descriptions for display
                if len(desc) > 70:
                    desc = desc[:67] + "..."
                print(f"    • {name:<30} {desc}")
        print()

    # Also dump full JSON if --json flag passed
    if "--json" in sys.argv:
        print("\n--- JSON ---")
        print(json.dumps(tools, indent=2))


def _cmd_run() -> None:
    from main import main
    main()


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "run"

    if cmd in ("tools", "list-tools", "list"):
        _cmd_tools()
    elif cmd in ("run", "start", "server"):
        _cmd_run()
    elif cmd in ("-h", "--help", "help"):
        print(__doc__)
    else:
        # Unknown arg — pass through to server (e.g. launched by MCP client)
        _cmd_run()


if __name__ == "__main__":
    main()
