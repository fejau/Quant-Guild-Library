"""Atomic JSON store for immutable staged order intents."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "staged_orders.json"
_LOCK = threading.RLock()

INTENT_FIELDS = (
    "account_id",
    "symbol",
    "conid",
    "side",
    "quantity",
    "order_type",
    "limit_price",
    "tif",
    "outside_rth",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def intent_hash(intent: dict[str, Any]) -> str:
    canonical = {key: intent.get(key) for key in INTENT_FIELDS}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class OrderStore:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "orders": []}
        with self.path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
            raise RuntimeError("Staged order store has an invalid format")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def create(
        self,
        intent: dict[str, Any],
        *,
        ttl_seconds: int,
        rationale: str = "",
        reference_price: float | None = None,
    ) -> dict[str, Any]:
        now = _now()
        order = {
            "id": f"ord_{uuid.uuid4().hex}",
            **{key: intent.get(key) for key in INTENT_FIELDS},
            "intent_hash": intent_hash(intent),
            "status": "staged",
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=ttl_seconds)),
            "reference_price": reference_price,
            "estimated_notional": (
                round(float(reference_price) * int(intent["quantity"]), 2)
                if reference_price
                else None
            ),
            "rationale": str(rationale or "")[:1000],
            "events": [{"at": _iso(now), "type": "staged"}],
        }
        with _LOCK:
            data = self._read()
            data["orders"].insert(0, order)
            data["orders"] = data["orders"][:200]
            self._write(data)
        return deepcopy(order)

    def list(self) -> list[dict[str, Any]]:
        with _LOCK:
            data = self._read()
            changed = False
            now = _now()
            for order in data["orders"]:
                if order.get("status") != "staged":
                    continue
                expires = datetime.fromisoformat(
                    str(order["expires_at"]).replace("Z", "+00:00")
                )
                if expires <= now:
                    order["status"] = "expired"
                    order.setdefault("events", []).append(
                        {"at": _iso(now), "type": "expired"}
                    )
                    changed = True
            if changed:
                self._write(data)
            return deepcopy(data["orders"])

    def get(self, order_id: str) -> dict[str, Any] | None:
        return next((row for row in self.list() if row.get("id") == order_id), None)

    def transition(
        self,
        order_id: str,
        *,
        from_status: str,
        to_status: str,
        event: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with _LOCK:
            data = self._read()
            for order in data["orders"]:
                if order.get("id") != order_id:
                    continue
                if order.get("status") != from_status:
                    raise RuntimeError(
                        f"Order is {order.get('status')}, expected {from_status}"
                    )
                if intent_hash(order) != order.get("intent_hash"):
                    raise RuntimeError("Staged order intent was modified")
                order["status"] = to_status
                if fields:
                    for key, value in fields.items():
                        if key in INTENT_FIELDS or key == "intent_hash":
                            raise RuntimeError(f"Cannot modify immutable field: {key}")
                        order[key] = value
                item = {"at": _iso(_now()), "type": to_status}
                if event:
                    item.update(event)
                order.setdefault("events", []).append(item)
                self._write(data)
                return deepcopy(order)
        raise KeyError(f"Unknown staged order: {order_id}")
