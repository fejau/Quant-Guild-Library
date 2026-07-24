"""Research-only portfolio review policy."""

from __future__ import annotations

THESIS_AUTONOMY_POLICY = """
PORTFOLIO RESEARCH POLICY:
- Broker facts must come from tools; never invent prices, positions, orders, or fills.
- Saved objectives constrain recommendations but never authorize a transaction.
- Automated reviews are research-only: never stage or submit an order.
- A human may explicitly ask for an order proposal during an interactive session.
  In an enabled staging mode, that proposal remains unsubmitted until separately
  approved in the local UI. In readonly mode, provide analysis only.
- Do not invent tickers merely to deploy idle cash.
""".strip()

THESIS_AUTONOMY_BLURB = (
    "Review portfolio facts and material risks. Automation is research-only; "
    "never stage or submit an order."
)


def auto_sweep_prompt(*, interval_label: str | None = None) -> str:
    when = f"every {interval_label}" if interval_label else "scheduled"
    return f"""PORTFOLIO RESEARCH REVIEW ({when}).

Read current positions, balances, working orders, saved theses, and objectives.
Identify material concentration, cash-floor, thesis, or target changes. Keep the
answer concise and distinguish broker facts from judgment.

This is research-only. Never call stage_equity_order, never submit or cancel an
order, never invent new tickers to consume cash, and never claim any trade occurred."""


def build_auto_sweep_context(
    holdings: list[dict],
    *,
    goals: dict | None = None,
    nav: float | None = None,
    cash: float | None = None,
    open_orders: list[dict] | None = None,
) -> str:
    goals = goals or {}
    lines = [
        "Research review context:",
        f"NAV={nav!r}; cash={cash!r}",
        f"Goals={goals!r}",
        f"Working orders={open_orders or []!r}",
        "Positions:",
    ]
    for holding in holdings:
        if holding.get("symbol") == "—":
            continue
        thesis = holding.get("thesis") or {}
        lines.append(
            f"- {holding.get('symbol')}: qty={holding.get('qty')}, "
            f"last={holding.get('last')}, weight={holding.get('weight')}%, "
            f"thesis_target={thesis.get('target')}, "
            f"thesis_saved_at={thesis.get('saved_at')}"
        )
    lines.append("Constraint: research only; do not stage or submit orders.")
    return "\n".join(lines)
