"""OpenAI tool schemas for research and human-approved order staging."""

from __future__ import annotations

from config import Settings, get_settings


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


READ_TOOLS = [
    _tool(
        "qualify_stock",
        "Resolve an exact stock symbol to an IBKR contract and conid.",
        {
            "symbol": {"type": "string"},
            "exchange": {"type": "string", "default": "SMART"},
            "currency": {"type": "string", "default": "USD"},
        },
        ["symbol"],
    ),
    _tool(
        "get_market_snapshot",
        "Read the current IBKR bid, ask, last, close, high, low and volume snapshot.",
        {"symbol": {"type": "string"}},
        ["symbol"],
    ),
    _tool(
        "get_historical_bars",
        "Read IBKR historical OHLCV bars for research.",
        {
            "symbol": {"type": "string"},
            "duration": {"type": "string", "default": "1 M"},
            "bar_size": {"type": "string", "default": "1 day"},
            "what_to_show": {"type": "string", "default": "TRADES"},
            "use_rth": {"type": "boolean", "default": True},
            "end_datetime": {"type": "string", "default": ""},
        },
        ["symbol"],
    ),
    _tool("get_account_summary", "Read the configured account's balances and NAV.", {}),
    _tool("get_positions", "Read positions for the explicitly configured IBKR account.", {}),
    _tool("get_portfolio", "Read marked portfolio positions for the configured account.", {}),
    _tool("get_open_orders", "Read working orders for the configured account.", {}),
    _tool(
        "get_portfolio_objectives",
        "Load the user's saved portfolio goals and risk constraints.",
        {},
    ),
    _tool(
        "propose_position_size",
        "Calculate a non-binding position size. This does not stage or submit an order.",
        {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "conviction": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "default": "medium",
            },
            "target_weight_pct": {"type": "number"},
            "stop_price": {"type": "number"},
            "entry_price": {"type": "number"},
            "liquidate": {"type": "boolean", "default": False},
        },
        ["symbol", "side"],
    ),
    _tool("get_brain_summary", "Read saved goals, theses, and decision notes.", {}),
    _tool(
        "save_thesis",
        "Save or revise a research thesis. This never sends an order.",
        {
            "symbol": {"type": "string"},
            "narrative": {"type": "string"},
            "conviction": {"type": "string"},
            "target": {"type": "number"},
            "entry": {"type": "number"},
            "cost_basis": {"type": "number"},
            "horizon": {"type": "string"},
            "notes": {"type": "string"},
        },
        ["symbol", "narrative", "conviction"],
    ),
    _tool(
        "record_trade",
        "Record a recommendation or observed trade in local memory. This never sends an order.",
        {
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "qty": {"type": "number"},
            "price": {"type": "number"},
            "rationale": {"type": "string"},
            "thesis_id": {"type": "string"},
            "status": {"type": "string"},
        },
        ["symbol", "side", "qty"],
    ),
]

STAGE_TOOL = _tool(
    "stage_equity_order",
    (
        "Create a short-lived order proposal for separate human review. "
        "This never submits to IBKR and is unavailable in readonly mode."
    ),
    {
        "symbol": {"type": "string"},
        "side": {"type": "string", "enum": ["BUY", "SELL"]},
        "quantity": {"type": "integer", "minimum": 1},
        "order_type": {"type": "string", "enum": ["LMT", "MKT"], "default": "LMT"},
        "limit_price": {"type": "number", "exclusiveMinimum": 0},
        "tif": {"type": "string", "enum": ["DAY", "GTC"], "default": "DAY"},
        "outside_rth": {"type": "boolean", "default": False},
        "rationale": {"type": "string"},
    },
    ["symbol", "side", "quantity"],
)


def tool_definitions(settings: Settings | None = None) -> list[dict]:
    active = settings or get_settings(require_openai=False)
    return [*READ_TOOLS, STAGE_TOOL] if active.staging_enabled else list(READ_TOOLS)


# Kept for compatibility with callers/tests that import this constant. It is the
# safe, readonly set; TradingAgent calls tool_definitions() for the active mode.
TOOL_DEFINITIONS = READ_TOOLS

SYSTEM_PROMPT = """You are an IBKR-connected portfolio research assistant.

The account is explicitly scoped by the server. Use broker tools to inspect facts,
then provide concise, evidence-based analysis. Never invent prices, positions,
orders, order ids, submissions, or fills.

Safety boundary:
- You cannot submit or cancel broker orders.
- In readonly mode, you cannot even stage an order.
- In paper/live staging mode, stage_equity_order only creates a proposal. Clearly
  say it is unsubmitted and requires separate human review in the local UI.
- Never claim that a staged proposal was approved, submitted, accepted, or filled.
- Never ask for or expose IBKR credentials, account ids, API keys, or secrets.
- Never infer a ticker and trade it merely because cash is available.

Research workflow:
1. Read current portfolio/account state when it affects the answer.
2. Use saved objectives as constraints, not permission to trade.
3. Separate observed broker facts from assumptions and recommendations.
4. Save theses only when the user requested research or a materially supported
   thesis update. Record trade notes as recommendations unless a broker read
   confirms another status.
5. If proposing an action, explain sizing and risks. In staging modes you may
   stage only an explicit, fully specified proposal within server controls.
"""
