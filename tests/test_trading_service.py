from __future__ import annotations

from dataclasses import replace

from config import LIVE_CONFIRM_VALUE, get_settings
from trading.service import approval_phrase, stage_equity_order, submit_staged_order
from trading.store import OrderStore


class FakeGateway:
    def __init__(self, submit_response=None) -> None:
        self.submit_response = submit_response or [{"order_id": "broker-1", "order_status": "Submitted"}]
        self.submissions = 0

    def resolve_contract(self, symbol):
        return {"symbol": symbol, "conid": 265598}

    def snapshot(self, conid):
        return {"conid": conid, "bid": 99.0, "ask": 100.0, "last": 99.5}

    def session(self):
        return {"ok": True}

    def require_account(self):
        return "U123456"

    def positions(self):
        return [
            {
                "symbol": "AAPL",
                "position": 10.0,
                "marketValue": 995.0,
            }
        ]

    def summary(self):
        return {"summary": {"netliquidation": {"amount": 10000.0}}}

    def open_orders(self):
        return []

    def whatif_order(self, order):
        return [{"amount": {"total": "100.00"}}]

    def submit_order(self, order):
        self.submissions += 1
        return self.submit_response


def _live_settings():
    return replace(
        get_settings(require_openai=False),
        ibkr_account_id="U123456",
        trading_mode="live",
        live_trading_enabled=True,
        live_trading_confirm=LIVE_CONFIRM_VALUE,
        allowed_symbols=frozenset({"AAPL"}),
        max_order_notional=500.0,
        max_position_pct=0.20,
        require_limit_orders=True,
    )


def _stage(store, gateway, settings):
    return stage_equity_order(
        "AAPL",
        "BUY",
        1,
        order_type="LMT",
        limit_price=100.0,
        settings=settings,
        gateway=gateway,
        store=store,
    )["order"]


def test_readonly_cannot_stage(tmp_path) -> None:
    settings = replace(_live_settings(), trading_mode="readonly")
    result = stage_equity_order(
        "AAPL",
        "BUY",
        1,
        order_type="LMT",
        limit_price=100.0,
        settings=settings,
        gateway=FakeGateway(),
        store=OrderStore(tmp_path / "orders.json"),
    )
    assert result["ok"] is False
    assert result["submitted"] is False


def test_wrong_human_phrase_never_submits(tmp_path) -> None:
    store = OrderStore(tmp_path / "orders.json")
    gateway = FakeGateway()
    settings = _live_settings()
    order = _stage(store, gateway, settings)
    result = submit_staged_order(
        order["id"],
        "wrong",
        settings=settings,
        gateway=gateway,
        store=store,
    )
    assert result["submitted"] is False
    assert gateway.submissions == 0


def test_broker_warning_is_never_auto_confirmed(tmp_path) -> None:
    warning = [{"id": "reply-1", "message": ["Price exceeds precautionary limit"]}]
    store = OrderStore(tmp_path / "orders.json")
    gateway = FakeGateway(submit_response=warning)
    settings = _live_settings()
    order = _stage(store, gateway, settings)
    result = submit_staged_order(
        order["id"],
        approval_phrase(order["id"]),
        settings=settings,
        gateway=gateway,
        store=store,
    )
    assert result["submitted"] is False
    assert result["broker_warning"] is True
    assert gateway.submissions == 1
    assert store.get(order["id"])["status"] == "broker_warning"


def test_exact_human_phrase_submits_exact_intent_once(tmp_path) -> None:
    store = OrderStore(tmp_path / "orders.json")
    gateway = FakeGateway()
    settings = _live_settings()
    order = _stage(store, gateway, settings)
    result = submit_staged_order(
        order["id"],
        approval_phrase(order["id"]),
        settings=settings,
        gateway=gateway,
        store=store,
    )
    assert result["ok"] is True
    assert result["submitted"] is True
    assert gateway.submissions == 1
    assert store.get(order["id"])["status"] == "submitted"

    retry = submit_staged_order(
        order["id"],
        approval_phrase(order["id"]),
        settings=settings,
        gateway=gateway,
        store=store,
    )
    assert retry["submitted"] is False
    assert gateway.submissions == 1


def test_sell_cannot_create_short(tmp_path) -> None:
    store = OrderStore(tmp_path / "orders.json")
    gateway = FakeGateway()
    settings = replace(_live_settings(), max_order_notional=2000.0)
    staged = stage_equity_order(
        "AAPL",
        "SELL",
        11,
        order_type="LMT",
        limit_price=100.0,
        settings=settings,
        gateway=gateway,
        store=store,
    )["order"]
    result = submit_staged_order(
        staged["id"],
        approval_phrase(staged["id"]),
        settings=settings,
        gateway=gateway,
        store=store,
    )
    assert result["submitted"] is False
    assert "exceed" in result["error"]
    assert gateway.submissions == 0
