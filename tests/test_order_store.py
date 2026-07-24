from __future__ import annotations

import json

import pytest

from trading.store import OrderStore


def _intent() -> dict:
    return {
        "account_id": "U123",
        "symbol": "AAPL",
        "conid": 265598,
        "side": "BUY",
        "quantity": 1,
        "order_type": "LMT",
        "limit_price": 100.0,
        "tif": "DAY",
        "outside_rth": False,
    }


def test_expired_order_cannot_transition(tmp_path) -> None:
    store = OrderStore(tmp_path / "orders.json")
    order = store.create(_intent(), ttl_seconds=-1, reference_price=100.0)
    assert store.get(order["id"])["status"] == "expired"
    with pytest.raises(RuntimeError, match="expected staged"):
        store.transition(
            order["id"],
            from_status="staged",
            to_status="submitted",
        )


def test_modified_intent_is_detected(tmp_path) -> None:
    path = tmp_path / "orders.json"
    store = OrderStore(path)
    order = store.create(_intent(), ttl_seconds=900, reference_price=100.0)
    payload = json.loads(path.read_text())
    payload["orders"][0]["quantity"] = 500
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="modified"):
        store.transition(
            order["id"],
            from_status="staged",
            to_status="submitted",
        )
