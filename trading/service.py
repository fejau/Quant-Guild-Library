"""Deterministic order controls, isolated from the language model."""

from __future__ import annotations

from typing import Any

from config import Settings, get_settings
from ib_bridge import CPGateway, get_gateway

from .store import OrderStore, intent_hash


def approval_phrase(order_id: str) -> str:
    return f"SUBMIT {order_id[-6:].upper()}"


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive whole number")
    number = int(value)
    if number <= 0 or float(value) != number:
        raise ValueError(f"{name} must be a positive whole number")
    return number


def _reference_price(snapshot: dict[str, Any], side: str) -> float | None:
    keys = ("ask", "last", "close", "bid") if side == "BUY" else (
        "bid",
        "last",
        "close",
        "ask",
    )
    for key in keys:
        value = snapshot.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _account_context(gateway: CPGateway) -> tuple[float | None, dict[str, float]]:
    payload = gateway.summary()
    summary = payload.get("summary") or {}
    node = summary.get("netliquidation") or {}
    value = node.get("amount") if isinstance(node, dict) else node
    try:
        nav = float(value)
    except (TypeError, ValueError):
        nav = None
    rates = {
        str(currency).upper(): float(row.get("exchangerate") or 1)
        for currency, row in (payload.get("ledger") or {}).items()
        if isinstance(row, dict)
    }
    rates["BASE"] = 1.0
    return nav, rates


def _normalize_intent(
    *,
    settings: Settings,
    gateway: CPGateway,
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "LMT",
    limit_price: float | None = None,
    tif: str = "DAY",
    outside_rth: bool = False,
) -> tuple[dict[str, Any], float]:
    ticker = str(symbol or "").strip().upper()
    side_u = str(side or "").strip().upper()
    kind = str(order_type or "").strip().upper()
    tif_u = str(tif or "").strip().upper()
    qty = _positive_int(quantity, "quantity")

    if not settings.staging_enabled:
        raise RuntimeError("Order staging is disabled in readonly mode")
    if ticker not in settings.allowed_symbols:
        raise RuntimeError(f"{ticker or 'Symbol'} is not in IBKR_ALLOWED_SYMBOLS")
    if side_u not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if kind not in {"LMT", "MKT"}:
        raise ValueError("order_type must be LMT or MKT")
    if settings.require_limit_orders and kind != "LMT":
        raise RuntimeError("This configuration requires limit orders")
    if tif_u not in {"DAY", "GTC"}:
        raise ValueError("tif must be DAY or GTC")
    if outside_rth:
        raise RuntimeError("Outside-RTH orders are disabled")
    if kind == "LMT" and (limit_price is None or float(limit_price) <= 0):
        raise ValueError("A positive limit_price is required for LMT orders")

    contract = gateway.resolve_contract(ticker)
    snapshot = gateway.snapshot(contract["conid"])
    mark = _reference_price(snapshot, side_u)
    reference = float(limit_price) if kind == "LMT" else mark
    if reference is None or reference <= 0:
        raise RuntimeError("IBKR returned no usable reference price")
    if qty * reference > settings.max_order_notional:
        raise RuntimeError(
            f"Estimated notional exceeds ${settings.max_order_notional:,.2f} limit"
        )

    return (
        {
            "account_id": settings.ibkr_account_id,
            "symbol": ticker,
            "conid": int(contract["conid"]),
            "side": side_u,
            "quantity": qty,
            "order_type": kind,
            "limit_price": round(float(limit_price), 4) if limit_price else None,
            "tif": tif_u,
            "outside_rth": False,
        },
        reference,
    )


def stage_equity_order(
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "LMT",
    limit_price: float | None = None,
    tif: str = "DAY",
    outside_rth: bool = False,
    rationale: str = "",
    *,
    settings: Settings | None = None,
    gateway: CPGateway | None = None,
    store: OrderStore | None = None,
) -> dict[str, Any]:
    """Stage, but never submit, a proposal. Safe to expose conditionally to AI."""
    try:
        active = settings or get_settings(require_openai=False)
        broker = gateway or get_gateway()
        intent, reference = _normalize_intent(
            settings=active,
            gateway=broker,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            tif=tif,
            outside_rth=outside_rth,
        )
        order = (store or OrderStore()).create(
            intent,
            ttl_seconds=active.stage_ttl_seconds,
            rationale=rationale,
            reference_price=reference,
        )
        return {
            "ok": True,
            "submitted": False,
            "message": "Proposal staged for separate human review",
            "order": order,
        }
    except Exception as exc:
        return {"ok": False, "submitted": False, "error": f"{type(exc).__name__}: {exc}"}


def _validate_submission(
    order: dict[str, Any],
    *,
    settings: Settings,
    gateway: CPGateway,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.submission_armed:
        raise RuntimeError("Trading submission gates are not fully armed")
    if order.get("account_id") != settings.ibkr_account_id:
        raise RuntimeError("Staged account does not match configured account")
    if order.get("symbol") not in settings.allowed_symbols:
        raise RuntimeError("Staged symbol is no longer allowlisted")
    if intent_hash(order) != order.get("intent_hash"):
        raise RuntimeError("Staged order intent was modified")

    session = gateway.session()
    if not session.get("ok"):
        raise RuntimeError(session.get("error") or "IBKR session is unavailable")
    account = gateway.require_account()
    if account != order["account_id"]:
        raise RuntimeError("Authenticated account does not match staged account")

    contract = gateway.resolve_contract(order["symbol"])
    if int(contract["conid"]) != int(order["conid"]):
        raise RuntimeError("Contract resolution changed; stage a new order")
    snapshot = gateway.snapshot(int(order["conid"]))
    mark = _reference_price(snapshot, order["side"])
    price = order.get("limit_price") if order["order_type"] == "LMT" else mark
    if price is None or float(price) <= 0:
        raise RuntimeError("No usable submission price")
    notional = int(order["quantity"]) * float(price)
    if notional > settings.max_order_notional:
        raise RuntimeError("Order exceeds current maximum notional")

    positions = gateway.positions()
    current = next(
        (row for row in positions if row.get("symbol") == order["symbol"]),
        None,
    )
    current_qty = float((current or {}).get("position") or 0)
    current_value = float((current or {}).get("marketValue") or 0)
    currency = str((current or {}).get("currency") or contract.get("currency") or "USD").upper()
    if (
        order["side"] == "SELL"
        and not settings.allow_shorting
        and int(order["quantity"]) > max(current_qty, 0)
    ):
        raise RuntimeError("SELL would exceed the current long position")

    nav, exchange_rates = _account_context(gateway)
    if nav is None or nav <= 0:
        raise RuntimeError("Net liquidation value is unavailable")
    fx = exchange_rates.get(currency, 1.0)
    current_value_base = current_value * fx
    notional_base = notional * fx
    post_value = (
        current_value_base + notional_base
        if order["side"] == "BUY"
        else max(0.0, current_value_base - notional_base)
    )
    if (
        order["side"] == "BUY"
        and post_value / nav > settings.max_position_pct + 1e-9
    ):
        raise RuntimeError("Post-trade position would exceed IBKR_MAX_POSITION_PCT")

    for working in gateway.open_orders():
        if (
            working.get("symbol") == order["symbol"]
            and working.get("action") == order["side"]
        ):
            raise RuntimeError("A same-side working order already exists")

    broker_order = {
        "acctId": account,
        "conid": int(order["conid"]),
        "orderType": order["order_type"],
        "side": order["side"],
        "tif": order["tif"],
        "quantity": int(order["quantity"]),
        "outsideRTH": False,
        "useAdaptive": False,
    }
    if order["order_type"] == "LMT":
        broker_order["price"] = float(order["limit_price"])
    return broker_order, {
        "notional_quote_currency": round(notional, 2),
        "notional_base_currency": round(notional_base, 2),
        "currency": currency,
        "nav_base_currency": round(nav, 2),
    }


def _first_response(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], dict) else {}
    if isinstance(payload, dict):
        return payload
    return {}


def submit_staged_order(
    order_id: str,
    confirmation: str,
    *,
    settings: Settings | None = None,
    gateway: CPGateway | None = None,
    store: OrderStore | None = None,
) -> dict[str, Any]:
    """Submit one exact staged intent after a separate human confirmation."""
    active_store = store or OrderStore()
    order = active_store.get(order_id)
    if not order:
        return {"ok": False, "submitted": False, "error": "Unknown staged order"}
    if order.get("status") != "staged":
        return {
            "ok": False,
            "submitted": False,
            "error": f"Order is {order.get('status')}, not staged",
        }
    if confirmation.strip().upper() != approval_phrase(order_id):
        return {
            "ok": False,
            "submitted": False,
            "error": "Human confirmation phrase did not match",
        }

    settings = settings or get_settings(require_openai=False)
    gateway = gateway or get_gateway()
    try:
        broker_order, checks = _validate_submission(
            order, settings=settings, gateway=gateway
        )
        whatif = gateway.whatif_order(broker_order)
        preflight = _first_response(whatif)
        if preflight.get("error") or preflight.get("errorMessage"):
            raise RuntimeError(
                f"IBKR what-if rejected order: "
                f"{preflight.get('error') or preflight.get('errorMessage')}"
            )
        if preflight.get("id") and (
            preflight.get("message") or preflight.get("messages")
        ):
            raise RuntimeError(
                "IBKR what-if returned a warning requiring broker confirmation; "
                "submission was stopped"
            )

        payload = gateway.submit_order(broker_order)
        first = _first_response(payload)
        messages = first.get("message") or first.get("messages")
        if first.get("id") and messages and not first.get("order_id") and not first.get("orderId"):
            updated = active_store.transition(
                order_id,
                from_status="staged",
                to_status="broker_warning",
                event={"broker_reply_id": str(first["id"])},
                fields={
                    "broker_response": payload,
                    "warning": messages,
                    "note": "Broker warning was not auto-confirmed",
                },
            )
            return {
                "ok": False,
                "submitted": False,
                "broker_warning": True,
                "error": "IBKR requires an additional warning confirmation; it was not auto-confirmed",
                "order": updated,
            }

        broker_id = first.get("order_id") or first.get("orderId")
        if not broker_id:
            raise RuntimeError("IBKR did not return an order id")
        updated = active_store.transition(
            order_id,
            from_status="staged",
            to_status="submitted",
            fields={
                "broker_order_id": broker_id,
                "broker_status": first.get("order_status") or first.get("status"),
                "broker_response": payload,
                "checks": checks,
            },
        )
        return {"ok": True, "submitted": True, "order": updated}
    except Exception as exc:
        return {
            "ok": False,
            "submitted": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
