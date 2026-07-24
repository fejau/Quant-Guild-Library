"""Map IBKR Client Portal data into the inherited dashboard shape."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from config import get_settings, trading_mode_status

from . import get_account_summary, get_gateway, get_portfolio

_CACHE_LOCK = threading.Lock()
_CACHE_AT = 0.0
_CACHE_RESULT: dict[str, Any] | None = None


def _money(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _summary_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        try:
            out[str(row.get("tag"))] = float(row.get("value"))
        except (TypeError, ValueError):
            continue
    return out


def _holdings(
    items: list[dict[str, Any]],
    nav: float | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        qty = float(item.get("position") or 0)
        if qty == 0:
            continue
        price = float(item.get("marketPrice") or 0)
        avg_cost = float(item.get("averageCost") or 0)
        value = float(item.get("marketValue") or qty * price)
        unrealized = float(item.get("unrealizedPNL") or 0)
        fx = float(
            item.get("reporting_exchange_rate")
            or item.get("base_exchange_rate")
            or 1
        )
        value_base = value * fx
        unrealized_base = unrealized * fx
        basis_base = abs(avg_cost * qty) * fx
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        group = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": symbol,
                "qty": 0.0,
                "last": price,
                "basis_base": 0.0,
                "mkt_value": 0.0,
                "unrealized_pnl": 0.0,
                "accounts": set(),
                "conids": set(),
                "sector": "",
            },
        )
        group["qty"] += qty
        group["last"] = price or group["last"]
        group["basis_base"] += basis_base
        group["mkt_value"] += value_base
        group["unrealized_pnl"] += unrealized_base
        if item.get("account"):
            group["accounts"].add(str(item["account"]))
        if item.get("conid") is not None:
            group["conids"].add(item["conid"])

    out = []
    for group in grouped.values():
        basis = group.pop("basis_base")
        accounts = sorted(group["accounts"])
        conids = sorted(group.pop("conids"))
        group["accounts"] = accounts
        group["account_count"] = len(accounts)
        group["conid"] = conids[0] if len(conids) == 1 else None
        group["avg_cost"] = (
            round(basis / abs(group["qty"]), 4) if group["qty"] else 0.0
        )
        group["mkt_value"] = round(group["mkt_value"], 2)
        group["unrealized_pnl"] = round(group["unrealized_pnl"], 2)
        group["pnl_pct"] = round(
            (group["unrealized_pnl"] / basis * 100) if basis else 0,
            2,
        )
        group["weight"] = round(
            (group["mkt_value"] / nav * 100) if nav else 0,
            2,
        )
        group["last"] = round(group["last"], 4)
        out.append(group)
    return sorted(out, key=lambda row: abs(row["mkt_value"]), reverse=True)


def _metrics(
    tags: dict[str, float],
    account_count: int,
    reporting_currency: str,
) -> list[dict[str, Any]]:
    nav = tags.get("NetLiquidation")
    cash = tags.get("TotalCashValue")
    unrealized = tags.get("UnrealizedPnL")
    gross = tags.get("GrossPositionValue")
    source = (
        f"{account_count} IBKR account{'s' if account_count != 1 else ''} "
        f"· {reporting_currency}"
    )
    return [
        {"id": "nav", "label": "PORTFOLIO NAV", "value": _money(nav), "delta": source, "tone": "neutral"},
        {"id": "cash", "label": "CASH", "value": _money(cash), "delta": source, "tone": "neutral"},
        {"id": "buying_power", "label": "BUYING POWER", "value": _money(tags.get("BuyingPower")), "delta": source, "tone": "neutral"},
        {"id": "unrealized", "label": "UNREALIZED P&L", "value": _money(unrealized, signed=True), "delta": source, "tone": "up" if (unrealized or 0) >= 0 else "down"},
        {"id": "day_pnl", "label": "REALIZED P&L", "value": _money(tags.get("RealizedPnL"), signed=True), "delta": source, "tone": "neutral"},
        {"id": "gross", "label": "GROSS EXPOSURE", "value": _money(gross), "delta": source, "tone": "neutral"},
    ]


def connection_info(*, connected: bool, error: str | None = None) -> dict[str, Any]:
    settings = get_settings(require_openai=False)
    parsed = urlparse(settings.gateway_url)
    status = trading_mode_status()
    return {
        "connected": connected,
        "host": parsed.hostname,
        "port": parsed.port,
        "client_id": None,
        "readonly": status["read_only"],
        "orders_allowed": status["submission_armed"],
        "order_mode": status,
        "mode": str(status["mode"]).upper(),
        "label": "IBKR Client Portal",
        "status_label": f"{'ONLINE' if connected else 'OFFLINE'} · {str(status['mode']).upper()}",
        "login_url": get_gateway().login_url,
        "error": error,
    }


def fetch_live_portfolio_for_ui() -> dict[str, Any]:
    global _CACHE_AT, _CACHE_RESULT
    with _CACHE_LOCK:
        if _CACHE_RESULT is not None and time.monotonic() - _CACHE_AT < 3:
            return deepcopy(_CACHE_RESULT)
        try:
            session = get_gateway().session()
            if not session.get("ok"):
                raise RuntimeError(session.get("error") or "IBKR session unavailable")
            summary = get_account_summary()
            if not summary.get("ok"):
                raise RuntimeError(summary.get("error") or "Account summary unavailable")
            if summary.get("aggregation_error"):
                raise RuntimeError(summary["aggregation_error"])
            portfolio = get_portfolio(account_context=summary)
            if not portfolio.get("ok"):
                raise RuntimeError(portfolio.get("error") or "Portfolio unavailable")
            tags = _summary_map(summary.get("summary") or [])
            nav = tags.get("NetLiquidation")
            cash = tags.get("TotalCashValue") or tags.get("AvailableFunds")
            account_count = int(summary.get("account_count") or 0)
            connection = connection_info(connected=True)
            connection["account_count"] = account_count
            connection["accounts"] = summary.get("accounts") or []
            connection["label"] = (
                f"IBKR Client Portal · {account_count} "
                f"account{'s' if account_count != 1 else ''}"
            )
            result = {
                "ok": True,
                "source": "ibkr",
                "holdings": _holdings(
                    portfolio.get("portfolio") or [],
                    nav,
                ),
                "metrics": _metrics(
                    tags,
                    account_count,
                    str(summary.get("reporting_currency") or ""),
                ),
                "nav": nav,
                "cash": cash,
                "accounts": summary.get("accounts") or [],
                "account_count": account_count,
                "account_summaries": summary.get("account_summaries") or [],
                "connection": connection,
            }
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            result = {
                "ok": False,
                "source": "error",
                "holdings": [],
                "metrics": [],
                "nav": None,
                "cash": None,
                "accounts": [],
                "account_count": 0,
                "account_summaries": [],
                "connection": connection_info(connected=False, error=error),
                "error": error,
            }
        _CACHE_AT = time.monotonic()
        _CACHE_RESULT = result
        return deepcopy(result)
