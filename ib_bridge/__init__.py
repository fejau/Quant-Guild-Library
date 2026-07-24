"""IBKR Client Portal Gateway bridge.

The public functions in this module preserve the original bot's read APIs, but
all traffic now goes through Felix's localhost-only Client Portal Gateway.
Order submission is deliberately private to ``trading.service`` and is never
registered as an AI tool.
"""

from __future__ import annotations

import threading
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from config import Settings, get_settings

_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOCK = threading.Lock()
_GATEWAY: "CPGateway | None" = None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    return float(match.group(0))


def _symbol(value: str) -> str:
    out = str(value or "").strip().upper()
    if not out or len(out) > 24:
        raise ValueError("A valid ticker symbol is required")
    return out


def _mask_account(account: str) -> str:
    return f"{account[:2]}…{account[-3:]}" if len(account) > 5 else "configured"


class CPGateway:
    """Small, account-pinned wrapper around IBKR's local Client Portal API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.settings = settings or get_settings(require_openai=False)
        self.base_url = self.settings.gateway_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in _ALLOWED_HOSTS:
            raise ValueError(
                "GATEWAY_URL must use http(s) on localhost; refusing a remote broker host"
            )
        self.account_id = self.settings.ibkr_account_id
        self.client = client or httpx.Client(
            base_url=self.base_url,
            verify=False,
            timeout=timeout,
        )

    @property
    def login_url(self) -> str:
        parsed = urlparse(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _json(self, response: httpx.Response) -> Any:
        response.raise_for_status()
        return response.json()

    def session(self) -> dict[str, Any]:
        try:
            response = self.client.post("/iserver/auth/status")
            if response.status_code != 200:
                return {
                    "ok": False,
                    "reachable": True,
                    "authenticated": False,
                    "status_code": response.status_code,
                    "error": "IBKR Gateway is reachable but not authenticated",
                }
            raw = response.json()
            authenticated = bool(raw.get("authenticated"))
            connected = raw.get("connected") is not False
            established = raw.get("established") is not False
            competing = bool(raw.get("competing"))
            ok = authenticated and connected and established and not competing
            return {
                "ok": ok,
                "reachable": True,
                "authenticated": authenticated,
                "connected": connected,
                "established": established,
                "competing": competing,
                "error": None if ok else "IBKR brokerage session is not fully established",
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "ok": False,
                "reachable": False,
                "authenticated": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def accounts(self) -> list[dict[str, Any]]:
        rows = self._json(self.client.get("/portfolio/accounts")) or []
        return [
            {
                "account_id": row.get("accountId") or row.get("id"),
                "alias": row.get("accountAlias") or row.get("alias") or row.get("desc"),
                "currency": row.get("currency"),
                "type": row.get("type") or row.get("accountVan"),
            }
            for row in rows
            if row.get("accountId") or row.get("id")
        ]

    def require_account(self) -> str:
        ids = {row["account_id"] for row in self.accounts()}
        if not self.account_id:
            if self.settings.trading_mode == "readonly":
                selected_response = self.client.get("/iserver/accounts")
                if selected_response.status_code == 200:
                    selected = (selected_response.json() or {}).get("selectedAccount")
                    if selected in ids:
                        return str(selected)
                if len(ids) == 1:
                    return next(iter(ids))
            raise RuntimeError(
                "IBKR_ACCOUNT_ID is required unless readonly mode can identify the "
                "gateway's currently selected account"
            )
        if self.account_id not in ids:
            raise RuntimeError(
                "Configured IBKR_ACCOUNT_ID is not present in the authenticated gateway session"
            )
        return self.account_id

    def select_account(self) -> str:
        account = self.require_account()
        response = self.client.post("/iserver/account", json={"acctId": account})
        response.raise_for_status()
        return account

    def resolve_contract(
        self, symbol: str, exchange: str = "SMART", currency: str = "USD"
    ) -> dict[str, Any]:
        ticker = _symbol(symbol)
        rows = self._json(
            self.client.get("/iserver/secdef/search", params={"symbol": ticker})
        ) or []
        exact = [
            row
            for row in rows
            if str(row.get("symbol") or "").upper() == ticker
            and str(row.get("assetClass") or row.get("secType") or "STK").upper()
            in {"STK", "ETF"}
        ]
        if not exact:
            raise RuntimeError(f"No exact stock contract found for {ticker}")
        preferred = next(
            (
                row
                for row in exact
                if str(row.get("currency") or currency).upper() == currency.upper()
            ),
            exact[0],
        )
        conid = preferred.get("conid")
        if conid is None:
            raise RuntimeError(f"IBKR returned no conid for {ticker}")
        return {
            "symbol": ticker,
            "conid": int(conid),
            "exchange": exchange.upper(),
            "currency": str(preferred.get("currency") or currency).upper(),
            "description": preferred.get("companyName")
            or preferred.get("description")
            or ticker,
            "asset_class": preferred.get("assetClass") or "STK",
        }

    def positions(self) -> list[dict[str, Any]]:
        account = self.require_account()
        out: list[dict[str, Any]] = []
        page = 0
        while True:
            rows = self._json(
                self.client.get(f"/portfolio/{account}/positions/{page}")
            ) or []
            if not rows:
                break
            for row in rows:
                symbol = str(
                    row.get("ticker")
                    or row.get("symbol")
                    or row.get("contractDesc")
                    or ""
                ).split()[0].upper()
                out.append(
                {
                    "symbol": symbol,
                        "conid": row.get("conid"),
                        "secType": row.get("assetClass") or "STK",
                        "currency": row.get("currency") or "USD",
                        "position": _number(row.get("position")) or 0.0,
                        "averageCost": _number(row.get("avgPrice")) or 0.0,
                        "marketPrice": _number(row.get("mktPrice")) or 0.0,
                        "marketValue": _number(row.get("mktValue")) or 0.0,
                        "unrealizedPNL": _number(row.get("unrealizedPnl")) or 0.0,
                    }
                )
            if len(rows) < 100:
                break
            page += 1
        return out

    def summary(self) -> dict[str, Any]:
        account = self.require_account()
        raw = self._json(self.client.get(f"/portfolio/{account}/summary")) or {}
        ledger_response = self.client.get(f"/portfolio/{account}/ledger")
        ledger = ledger_response.json() if ledger_response.status_code == 200 else {}
        return {"account": account, "summary": raw, "ledger": ledger}

    def open_orders(self) -> list[dict[str, Any]]:
        account = self.select_account()
        payload = self._json(self.client.get("/iserver/account/orders")) or {}
        rows = payload.get("orders") if isinstance(payload, dict) else payload
        out = []
        for row in rows or []:
            row_account = row.get("acct") or row.get("account") or row.get("accountId")
            if row_account and row_account != account:
                continue
            out.append(
                {
                    "orderId": row.get("orderId") or row.get("order_id"),
                    "symbol": str(row.get("ticker") or row.get("symbol") or "").upper(),
                    "action": str(row.get("side") or row.get("action") or "").upper(),
                    "totalQuantity": _number(
                        row.get("totalSize") or row.get("totalQuantity") or row.get("quantity")
                    ),
                    "filled": _number(row.get("filledQuantity") or row.get("filled")) or 0.0,
                    "remaining": _number(
                        row.get("remainingQuantity") or row.get("remaining")
                    ),
                    "orderType": row.get("orderType") or row.get("order_type"),
                    "lmtPrice": _number(row.get("price") or row.get("lmtPrice")),
                    "status": row.get("status") or row.get("order_status"),
                    "conid": row.get("conid"),
                }
            )
        return out

    def snapshot(self, conid: int) -> dict[str, Any]:
        fields = "31,55,70,71,73,84,86,7295"
        rows = self._json(
            self.client.get(
                "/iserver/marketdata/snapshot",
                params={"conids": str(conid), "fields": fields},
            )
        ) or []
        row = rows[0] if rows else {}
        return {
            "conid": conid,
            "symbol": row.get("55"),
            "last": _number(row.get("31")),
            "high": _number(row.get("70")),
            "low": _number(row.get("71")),
            "volume": _number(row.get("73")),
            "bid": _number(row.get("84")),
            "ask": _number(row.get("86")),
            "close": _number(row.get("7295")),
            "raw": row,
        }

    def history(
        self,
        conid: int,
        *,
        period: str = "1m",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> list[dict[str, Any]]:
        payload = self._json(
            self.client.get(
                "/iserver/marketdata/history",
                params={
                    "conid": conid,
                    "period": period,
                    "bar": bar,
                    "outsideRth": str(outside_rth).lower(),
                },
            )
        ) or {}
        rows = []
        for row in payload.get("data") or []:
            timestamp = row.get("t")
            date = (
                datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).isoformat()
                if timestamp
                else None
            )
            rows.append(
                {
                    "date": date,
                    "open": _number(row.get("o")),
                    "high": _number(row.get("h")),
                    "low": _number(row.get("l")),
                    "close": _number(row.get("c")),
                    "volume": (
                        (_number(row.get("v")) or 0.0) * 100
                        if row.get("v") is not None
                        else None
                    ),
                }
            )
        return rows

    # These methods are intentionally not exported to the AI executor.
    def whatif_order(self, order: dict[str, Any]) -> Any:
        account = self.select_account()
        return self._json(
            self.client.post(
                f"/iserver/account/{account}/orders/whatif",
                json={"orders": [order]},
            )
        )

    def submit_order(self, order: dict[str, Any]) -> Any:
        account = self.select_account()
        return self._json(
            self.client.post(
                f"/iserver/account/{account}/orders",
                json={"orders": [order]},
            )
        )


def get_gateway(*, fresh: bool = False) -> CPGateway:
    global _GATEWAY
    with _LOCK:
        if fresh or _GATEWAY is None:
            _GATEWAY = CPGateway()
        return _GATEWAY


def disconnect_ib() -> None:
    """Compatibility helper for the original smoke test."""
    global _GATEWAY
    with _LOCK:
        if _GATEWAY is not None:
            _GATEWAY.client.close()
        _GATEWAY = None


def qualify_stock(
    symbol: str, exchange: str = "SMART", currency: str = "USD"
) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "contract": get_gateway().resolve_contract(symbol, exchange, currency),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_market_snapshot(symbol: str) -> dict[str, Any]:
    try:
        gateway = get_gateway()
        contract = gateway.resolve_contract(symbol)
        return {"ok": True, **gateway.snapshot(contract["conid"])}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _history_period(duration: str) -> str:
    value = duration.strip().lower().replace(" ", "")
    number = "".join(ch for ch in value if ch.isdigit()) or "1"
    if value.endswith("d"):
        return f"{number}d"
    if value.endswith("w"):
        return f"{number}w"
    if value.endswith("y"):
        return f"{number}y"
    return f"{number}m"


def _history_bar(bar_size: str) -> str:
    value = bar_size.strip().lower()
    if "day" in value or value.endswith("d"):
        return "1d"
    if "hour" in value or value.endswith("h"):
        return "1h"
    if "5" in value and "min" in value:
        return "5min"
    return "1min"


def get_historical_bars(
    symbol: str,
    duration: str = "1 M",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    end_datetime: str = "",
) -> dict[str, Any]:
    del what_to_show, end_datetime
    try:
        gateway = get_gateway()
        contract = gateway.resolve_contract(symbol)
        bars = gateway.history(
            contract["conid"],
            period=_history_period(duration),
            bar=_history_bar(bar_size),
            outside_rth=not use_rth,
        )
        return {"ok": True, "symbol": contract["symbol"], "bars": bars}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_account_summary() -> dict[str, Any]:
    try:
        gateway = get_gateway()
        payload = gateway.summary()
        raw = payload["summary"]
        account = payload["account"]
        masked_account = _mask_account(account)
        key_map = {
            "netliquidation": "NetLiquidation",
            "totalcashvalue": "TotalCashValue",
            "availablefunds": "AvailableFunds",
            "buyingpower": "BuyingPower",
            "unrealizedpnl": "UnrealizedPnL",
            "realizedpnl": "RealizedPnL",
            "grosspositionvalue": "GrossPositionValue",
            "excessliquidity": "ExcessLiquidity",
        }
        rows = []
        for source, tag in key_map.items():
            node = raw.get(source) or {}
            value = node.get("amount") if isinstance(node, dict) else node
            if value is not None:
                rows.append(
                    {
                        "account": masked_account,
                        "tag": tag,
                        "value": value,
                        "currency": node.get("currency") if isinstance(node, dict) else None,
                    }
                )
        return {
            "ok": True,
            "accounts": [masked_account],
            "summary": rows,
            "ledger": {
                currency: {
                    key: value
                    for key, value in node.items()
                    if key
                    in {
                        "currency",
                        "cashbalance",
                        "netliquidationvalue",
                        "stockmarketvalue",
                        "unrealizedpnl",
                        "realizedpnl",
                        "exchangerate",
                    }
                }
                for currency, node in payload["ledger"].items()
                if isinstance(node, dict)
            },
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_positions() -> dict[str, Any]:
    try:
        rows = get_gateway().positions()
        return {"ok": True, "positions": rows}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_portfolio() -> dict[str, Any]:
    positions = get_positions()
    if not positions.get("ok"):
        return positions
    return {"ok": True, "portfolio": positions["positions"]}


def get_open_orders() -> dict[str, Any]:
    try:
        rows = get_gateway().open_orders()
        return {"ok": True, "open_orders": rows, "working_orders": rows}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def get_news_providers() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "News is not exposed by this Client Portal Gateway integration",
    }


def get_historical_news(**_: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "News is not exposed by this Client Portal Gateway integration",
    }


def get_news_article(**_: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "News is not exposed by this Client Portal Gateway integration",
    }
