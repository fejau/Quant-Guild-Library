"""Dispatch AI tool calls. There is intentionally no broker-submit handler."""

from __future__ import annotations

import json
from typing import Any, Callable

from brain import brain_overview, record_trade, upsert_thesis
from ib_bridge import (
    get_account_summary,
    get_historical_bars,
    get_market_snapshot,
    get_open_orders,
    get_portfolio,
    get_positions,
    qualify_stock,
)
from risk import get_portfolio_objectives, propose_position_size
Handler = Callable[..., dict[str, Any]]


def _get_brain_summary() -> dict[str, Any]:
    return {"ok": True, "brain": brain_overview()}


def _save_thesis(**kwargs: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "thesis": upsert_thesis(
            source="agent",
            supersede_active=True,
            **kwargs,
        ),
    }


def _record_trade(**kwargs: Any) -> dict[str, Any]:
    return {"ok": True, "trade": record_trade(source="agent", **kwargs)}


_READ_HANDLERS: dict[str, Handler] = {
    "qualify_stock": qualify_stock,
    "get_market_snapshot": get_market_snapshot,
    "get_historical_bars": get_historical_bars,
    "get_account_summary": get_account_summary,
    "get_positions": get_positions,
    "get_portfolio": get_portfolio,
    "get_open_orders": get_open_orders,
    "get_portfolio_objectives": get_portfolio_objectives,
    "propose_position_size": propose_position_size,
    "get_brain_summary": _get_brain_summary,
    "save_thesis": _save_thesis,
    "record_trade": _record_trade,
}


def available_tools() -> list[str]:
    return sorted(_READ_HANDLERS)


def execute_tool(name: str, arguments: dict[str, Any] | str | None) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return json.dumps({"ok": False, "error": f"Invalid tool arguments: {exc}"})
    args = arguments or {}
    if not isinstance(args, dict):
        return json.dumps({"ok": False, "error": "Tool arguments must be an object"})

    if name == "stage_equity_order":
        return json.dumps(
            {
                "ok": False,
                "submitted": False,
                "error": "Strategy chat cannot stage orders; use local Order Control",
            }
        )
    handler = _READ_HANDLERS.get(name)
    if handler is None:
        return json.dumps(
            {"ok": False, "error": f"Unknown or unavailable tool: {name}"}
        )
    try:
        return json.dumps(handler(**args), default=str)
    except TypeError as exc:
        return json.dumps({"ok": False, "error": f"Bad arguments for {name}: {exc}"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
