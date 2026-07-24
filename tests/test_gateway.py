from __future__ import annotations

from dataclasses import replace

import pytest

from config import get_settings
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
            }
        ],
        1000,
        {"USD": 1.4, "BASE": 1.0},
    )
    assert rows[0]["mkt_value"] == 140
    assert rows[0]["weight"] == 14
