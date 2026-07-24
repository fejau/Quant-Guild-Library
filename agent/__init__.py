"""Strategy chat backends."""

from agent.codex_backend import CodexStrategyAgent, codex_auth_status
from agent.loop import AgentResult, TradingAgent, ToolTrace
from config import Settings, get_settings


def get_strategy_agent(
    settings: Settings | None = None,
    *,
    allow_staging: bool = False,
):
    del allow_staging
    active = settings or get_settings(require_openai=False)
    if active.strategy_chat_provider == "codex":
        return CodexStrategyAgent(active)
    # Strategy chat is research-only for every provider. Order proposals are
    # entered explicitly in the separate local Order Control form.
    return TradingAgent(active, allow_staging=False)


__all__ = [
    "AgentResult",
    "CodexStrategyAgent",
    "TradingAgent",
    "ToolTrace",
    "codex_auth_status",
    "get_strategy_agent",
]
