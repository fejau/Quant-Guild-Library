from __future__ import annotations

from config import LIVE_CONFIRM_VALUE, get_settings


def _set_base(monkeypatch) -> None:
    monkeypatch.setenv("IBKR_ACCOUNT_ID", "U123456")
    monkeypatch.setenv("IBKR_ALLOWED_SYMBOLS", "AAPL,SPY")
    monkeypatch.setenv("IBKR_MAX_ORDER_NOTIONAL", "500")
    monkeypatch.setenv("IBKR_MAX_POSITION_PCT", "0.05")
    monkeypatch.setenv("IBKR_STAGE_TTL_SECONDS", "900")


def test_readonly_is_never_armed(monkeypatch) -> None:
    _set_base(monkeypatch)
    monkeypatch.setenv("IBKR_TRADING_MODE", "readonly")
    monkeypatch.setenv("IBKR_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("IBKR_LIVE_TRADING_CONFIRM", LIVE_CONFIRM_VALUE)
    settings = get_settings(require_openai=False)
    assert settings.staging_enabled is False
    assert settings.submission_armed is False


def test_live_requires_every_gate(monkeypatch) -> None:
    _set_base(monkeypatch)
    monkeypatch.setenv("IBKR_TRADING_MODE", "live")
    monkeypatch.setenv("IBKR_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("IBKR_LIVE_TRADING_CONFIRM", "wrong")
    assert get_settings(require_openai=False).submission_armed is False

    monkeypatch.setenv("IBKR_LIVE_TRADING_CONFIRM", LIVE_CONFIRM_VALUE)
    assert get_settings(require_openai=False).submission_armed is True


def test_paper_requires_du_account(monkeypatch) -> None:
    _set_base(monkeypatch)
    monkeypatch.setenv("IBKR_TRADING_MODE", "paper")
    monkeypatch.setenv("IBKR_PAPER_TRADING_ENABLED", "true")
    assert get_settings(require_openai=False).submission_armed is False
    monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU123456")
    assert get_settings(require_openai=False).submission_armed is True
