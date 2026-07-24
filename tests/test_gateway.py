from __future__ import annotations

import json
from dataclasses import replace

import pytest

from config import get_settings
import ib_bridge
from ib_bridge import CPGateway
from ib_bridge.ui_portfolio import _holdings


def test_remote_gateway_is_rejected() -> None:
    settings = replace(
        get_settings(require_openai=False),
        gateway_url="https://broker.example/v1/api",
    )
    with pytest.raises(ValueError, match="localhost"):
        CPGateway(settings)


def test_portfolio_weight_converts_to_base_currency() -> None:
    rows = _holdings(
        [
            {
                "symbol": "AAPL",
                "position": 1,
                "marketPrice": 100,
                "marketValue": 100,
                "averageCost": 90,
                "unrealizedPNL": 10,
                "currency": "USD",
                "base_exchange_rate": 1.4,
                "account": "U1…001",
            }
        ],
        1000,
    )
    assert rows[0]["mkt_value"] == 140
    assert rows[0]["weight"] == 14


def test_all_accounts_are_masked_and_aggregated_in_reporting_currency(
    monkeypatch,
) -> None:
    active_settings = replace(
        get_settings(require_openai=False),
        ibkr_reporting_currency="CAD",
    )

    class Gateway:
        settings = active_settings

        def accounts(self):
            return [
                {"account_id": "U100001"},
                {"account_id": "U200002"},
            ]

        def summary(self, account):
            if account == "U100001":
                return {
                    "account": account,
                    "summary": {
                        "netliquidation": {"amount": 100, "currency": "USD"},
                        "totalcashvalue": {"amount": 25, "currency": "USD"},
                    },
                    "ledger": {
                        "USD": {"currency": "USD", "exchangerate": 1},
                    },
                }
            return {
                "account": account,
                "summary": {
                    "netliquidation": {"amount": 100, "currency": "CAD"},
                    "totalcashvalue": {"amount": 50, "currency": "CAD"},
                },
                "ledger": {
                    "CAD": {"currency": "CAD", "exchangerate": 1},
                    "USD": {"currency": "USD", "exchangerate": 1.4},
                },
            }

        def positions(self, account):
            if account == "U100001":
                return [
                    {
                        "symbol": "AAPL",
                        "position": 1,
                        "marketValue": 100,
                        "currency": "USD",
                    }
                ]
            return []

    gateway = Gateway()
    monkeypatch.setattr(ib_bridge, "get_gateway", lambda: gateway)

    summary = ib_bridge.get_account_summary(all_accounts=True)
    nav = next(
        row["value"]
        for row in summary["summary"]
        if row["tag"] == "NetLiquidation"
    )
    portfolio = ib_bridge.get_portfolio(
        all_accounts=True,
        account_context=summary,
    )

    assert summary["account_count"] == 2
    assert summary["accounts"] == ["U1…001", "U2…002"]
    assert summary["reporting_currency"] == "CAD"
    assert nav == pytest.approx(240)
    assert portfolio["portfolio"][0]["reporting_exchange_rate"] == pytest.approx(1.4)
    assert "U100001" not in json.dumps({"summary": summary, "portfolio": portfolio})
