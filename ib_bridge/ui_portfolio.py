"""Map IBKR Client Portal data into the inherited dashboard shape."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from config import get_settings, trading_mode_status

from . import get_account_summary, get_gateway, get_portfolio


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
    exchange_rates: dict[str, float],
) -> list[dict[str, Any]]:
    out = []
    for item in items:
        qty = float(item.get("position") or 0)
        if qty == 0:
            continue
        price = float(item.get("marketPrice") or 0)
        avg_cost = float(item.get("averageCost") or 0)
        value = float(item.get("marketValue") or qty * price)
        unrealized = float(item.get("unrealizedPNL") or 0)
        currency = str(item.get("currency") or "BASE").upper()
        fx = exchange_rates.get(currency, 1.0)
        value_base = value * fx
        basis = abs(avg_cost * qty)
        out.append(
            {
                "symbol": str(item.get("symbol") or "").upper(),
                "name": str(item.get("symbol") or "").upper(),
                "qty": qty,
                "last": round(price, 4),
                "avg_cost": round(avg_cost, 4),
                "mkt_value": round(value_base, 2),
                "pnl_pct": round((unrealized / basis * 100) if basis else 0, 2),
                "weight": round((value_base / nav * 100) if nav else 0, 2),
                "sector": "",
                "unrealized_pnl": round(unrealized, 2),
                "conid": item.get("conid"),
            }
        )
    return sorted(out, key=lambda row: abs(row["mkt_value"]), reverse=True)


def _metrics(tags: dict[str, float]) -> list[dict[str, Any]]:
    nav = tags.get("NetLiquidation")
    cash = tags.get("TotalCashValue")
    unrealized = tags.get("UnrealizedPnL")
    gross = tags.get("GrossPositionValue")
    return [
        {"id": "nav", "label": "PORTFOLIO NAV", "value": _money(nav), "delta": "IBKR", "tone": "neutral"},
        {"id": "cash", "label": "CASH", "value": _money(cash), "delta": "IBKR", "tone": "neutral"},
        {"id": "buying_power", "label": "BUYING POWER", "value": _money(tags.get("BuyingPower")), "delta": "IBKR", "tone": "neutral"},
        {"id": "unrealized", "label": "UNREALIZED P&L", "value": _money(unrealized, signed=True), "delta": "IBKR", "tone": "up" if (unrealized or 0) >= 0 else "down"},
        {"id": "day_pnl", "label": "REALIZED P&L", "value": _money(tags.get("RealizedPnL"), signed=True), "delta": "IBKR", "tone": "neutral"},
        {"id": "gross", "label": "GROSS EXPOSURE", "value": _money(gross), "delta": "IBKR", "tone": "neutral"},
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
    try:
        session = get_gateway().session()
        if not session.get("ok"):
            raise RuntimeError(session.get("error") or "IBKR session unavailable")
        summary = get_account_summary()
        if not summary.get("ok"):
            raise RuntimeError(summary.get("error") or "Account summary unavailable")
        portfolio = get_portfolio()
        if not portfolio.get("ok"):
            raise RuntimeError(portfolio.get("error") or "Portfolio unavailable")
        tags = _summary_map(summary.get("summary") or [])
        exchange_rates = {
            str(currency).upper(): float(node.get("exchangerate") or 1)
            for currency, node in (summary.get("ledger") or {}).items()
            if isinstance(node, dict)
        }
        exchange_rates["BASE"] = 1.0
        nav = tags.get("NetLiquidation")
        cash = tags.get("TotalCashValue") or tags.get("AvailableFunds")
        return {
            "ok": True,
            "source": "ibkr",
            "holdings": _holdings(
                portfolio.get("portfolio") or [],
                nav,
                exchange_rates,
            ),
            "metrics": _metrics(tags),
            "nav": nav,
            "cash": cash,
            "accounts": summary.get("accounts") or [],
            "connection": connection_info(connected=True),
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return {
            "ok": False,
            "source": "error",
            "holdings": [],
            "metrics": [],
            "nav": None,
            "cash": None,
            "accounts": [],
            "connection": connection_info(connected=False, error=error),
            "error": error,
        }
