from __future__ import annotations

from dataclasses import replace

from agent.schemas import tool_definitions
from config import get_settings


def _names(settings) -> set[str]:
    return {tool["function"]["name"] for tool in tool_definitions(settings)}


def test_readonly_has_no_order_capability() -> None:
    settings = replace(get_settings(require_openai=False), trading_mode="readonly")
    names = _names(settings)
    assert "stage_equity_order" not in names
    assert all("place" not in name and "submit" not in name and "cancel" not in name for name in names)


def test_trading_modes_do_not_give_chat_staging() -> None:
    settings = replace(get_settings(require_openai=False), trading_mode="paper")
    names = _names(settings)
    assert "stage_equity_order" not in names
    assert "place_equity_order" not in names
    assert "cancel_order" not in names
