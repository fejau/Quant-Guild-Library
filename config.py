"""Fail-closed configuration for the IBKR Client Portal Gateway integration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_ENV_PATH = PROJECT_ROOT / ".env"
LIVE_CONFIRM_VALUE = "I_UNDERSTAND_LIVE_IBKR_RISK"
VALID_TRADING_MODES = frozenset({"readonly", "paper", "live"})
VALID_CHAT_PROVIDERS = frozenset({"codex", "openai"})
SHARED_IBKR_KEYS = frozenset({"GATEWAY_URL", "IBKR_ACCOUNT_ID"})


def _env_values() -> dict[str, str]:
    """
    Resolve configuration without copying secrets between projects.

    Precedence:
      process environment > this project's .env > shared Fable .env
    """
    local_raw = {
        key: str(value)
        for key, value in dotenv_values(LOCAL_ENV_PATH).items()
        if value is not None
    }
    shared: dict[str, str] = {}
    shared_path = local_raw.get("IBKR_SHARED_ENV_FILE") or os.environ.get(
        "IBKR_SHARED_ENV_FILE", ""
    )
    if shared_path:
        path = Path(shared_path).expanduser()
        if path.is_file():
            shared = {
                key: str(value)
                for key, value in dotenv_values(path).items()
                if value is not None and key in SHARED_IBKR_KEYS
            }
    merged = {**shared, **local_raw}
    merged.update({key: str(value) for key, value in os.environ.items()})
    return merged


def _bool(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _symbols(raw: str | None) -> frozenset[str]:
    return frozenset(
        token.strip().upper()
        for token in (raw or "").split(",")
        if token.strip()
    )


@dataclass(frozen=True)
class Settings:
    strategy_chat_provider: str
    codex_bin: str
    codex_chat_model: str
    codex_reasoning_effort: str
    codex_timeout_seconds: int
    openai_api_key: str
    openai_model: str
    agent_max_iterations: int
    gateway_url: str
    ibkr_reporting_currency: str
    ibkr_account_id: str
    trading_mode: str
    live_trading_enabled: bool
    live_trading_confirm: str
    paper_trading_enabled: bool
    allowed_symbols: frozenset[str]
    max_order_notional: float
    max_position_pct: float
    allow_shorting: bool
    require_limit_orders: bool
    stage_ttl_seconds: int
    app_host: str
    app_port: int
    app_debug: bool

    @property
    def submission_armed(self) -> bool:
        if not self.ibkr_account_id or not self.allowed_symbols:
            return False
        if self.trading_mode == "paper":
            return self.paper_trading_enabled and self.ibkr_account_id.upper().startswith(
                "DU"
            )
        if self.trading_mode == "live":
            return (
                self.live_trading_enabled
                and self.live_trading_confirm == LIVE_CONFIRM_VALUE
                and not self.ibkr_account_id.upper().startswith("DU")
            )
        return False

    @property
    def staging_enabled(self) -> bool:
        return self.trading_mode in {"paper", "live"}


def get_settings(*, require_openai: bool = True) -> Settings:
    values = _env_values()
    chat_provider = values.get("STRATEGY_CHAT_PROVIDER", "codex").strip().lower()
    if chat_provider not in VALID_CHAT_PROVIDERS:
        raise RuntimeError("STRATEGY_CHAT_PROVIDER must be one of: codex, openai")
    mode = values.get("IBKR_TRADING_MODE", "readonly").strip().lower()
    if mode not in VALID_TRADING_MODES:
        raise RuntimeError(
            "IBKR_TRADING_MODE must be one of: readonly, paper, live"
        )

    key = values.get("OPENAI_API_KEY", "").strip()
    if require_openai and chat_provider == "openai" and not key:
        raise RuntimeError(
            "OPENAI_API_KEY is required when STRATEGY_CHAT_PROVIDER=openai."
        )

    max_notional = _float(values, "IBKR_MAX_ORDER_NOTIONAL", 500.0)
    max_position_pct = _float(values, "IBKR_MAX_POSITION_PCT", 0.05)
    stage_ttl = _int(values, "IBKR_STAGE_TTL_SECONDS", 900)
    if max_notional <= 0:
        raise RuntimeError("IBKR_MAX_ORDER_NOTIONAL must be positive")
    if not 0 < max_position_pct <= 1:
        raise RuntimeError("IBKR_MAX_POSITION_PCT must be between 0 and 1")
    if not 60 <= stage_ttl <= 86400:
        raise RuntimeError("IBKR_STAGE_TTL_SECONDS must be between 60 and 86400")
    codex_timeout = _int(values, "CODEX_CHAT_TIMEOUT_SECONDS", 180)
    if not 30 <= codex_timeout <= 600:
        raise RuntimeError("CODEX_CHAT_TIMEOUT_SECONDS must be between 30 and 600")
    reporting_currency = values.get("IBKR_REPORTING_CURRENCY", "CAD").strip().upper()
    if len(reporting_currency) != 3 or not reporting_currency.isalpha():
        raise RuntimeError("IBKR_REPORTING_CURRENCY must be a 3-letter currency code")

    return Settings(
        strategy_chat_provider=chat_provider,
        codex_bin=values.get("CODEX_BIN", "codex").strip(),
        codex_chat_model=values.get(
            "CODEX_CHAT_MODEL", "gpt-5.4"
        ).strip(),
        codex_reasoning_effort=values.get(
            "CODEX_REASONING_EFFORT", "medium"
        ).strip(),
        codex_timeout_seconds=codex_timeout,
        openai_api_key=key,
        openai_model=values.get("OPENAI_MODEL", "gpt-4o").strip(),
        agent_max_iterations=_int(values, "AGENT_MAX_ITERATIONS", 12),
        gateway_url=values.get(
            "GATEWAY_URL", "https://localhost:5001/v1/api"
        ).strip(),
        ibkr_reporting_currency=reporting_currency,
        ibkr_account_id=values.get("IBKR_ACCOUNT_ID", "").strip(),
        trading_mode=mode,
        live_trading_enabled=_bool(values, "IBKR_LIVE_TRADING_ENABLED"),
        live_trading_confirm=values.get(
            "IBKR_LIVE_TRADING_CONFIRM", ""
        ).strip(),
        paper_trading_enabled=_bool(values, "IBKR_PAPER_TRADING_ENABLED"),
        allowed_symbols=_symbols(values.get("IBKR_ALLOWED_SYMBOLS")),
        max_order_notional=max_notional,
        max_position_pct=max_position_pct,
        allow_shorting=_bool(values, "IBKR_ALLOW_SHORTING"),
        require_limit_orders=_bool(
            values, "IBKR_REQUIRE_LIMIT_ORDERS", default=True
        ),
        stage_ttl_seconds=stage_ttl,
        app_host=values.get("APP_HOST", "127.0.0.1").strip(),
        app_port=_int(values, "APP_PORT", 5050),
        app_debug=_bool(values, "APP_DEBUG"),
    )


def _masked_account(account_id: str) -> str | None:
    if not account_id:
        return None
    if len(account_id) <= 4:
        return "*" * len(account_id)
    return f"{account_id[:2]}…{account_id[-3:]}"


def trading_mode_status() -> dict[str, object]:
    settings = get_settings(require_openai=False)
    blockers: list[str] = []
    if settings.trading_mode == "readonly":
        blockers.append("mode_is_readonly")
    if settings.trading_mode == "paper":
        if not settings.paper_trading_enabled:
            blockers.append("paper_gate_disabled")
        if settings.ibkr_account_id and not settings.ibkr_account_id.upper().startswith(
            "DU"
        ):
            blockers.append("configured_account_is_not_paper")
    if settings.trading_mode == "live":
        if not settings.live_trading_enabled:
            blockers.append("live_gate_disabled")
        if settings.live_trading_confirm != LIVE_CONFIRM_VALUE:
            blockers.append("live_confirmation_missing")
        if settings.ibkr_account_id.upper().startswith("DU"):
            blockers.append("configured_account_is_paper")
    if not settings.ibkr_account_id:
        blockers.append("account_id_missing")
    if not settings.allowed_symbols:
        blockers.append("symbol_allowlist_empty")

    return {
        "mode": settings.trading_mode,
        "read_only": settings.trading_mode == "readonly",
        "staging_enabled": settings.staging_enabled,
        "submission_armed": settings.submission_armed,
        "account": _masked_account(settings.ibkr_account_id),
        "allowed_symbols": sorted(settings.allowed_symbols),
        "max_order_notional": settings.max_order_notional,
        "max_position_pct": settings.max_position_pct,
        "allow_shorting": settings.allow_shorting,
        "require_limit_orders": settings.require_limit_orders,
        "blockers": blockers,
    }


# Compatibility names used by the original UI and risk layer.
def order_mode_status() -> dict[str, object]:
    return trading_mode_status()


def orders_allowed() -> bool:
    return bool(trading_mode_status()["submission_armed"])


def get_max_order_notional() -> float:
    return get_settings(require_openai=False).max_order_notional
