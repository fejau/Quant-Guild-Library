"""Optional smoke test: read-only LLM tool loop against the local IBKR Gateway."""

from __future__ import annotations

from agent import get_strategy_agent
from ib_bridge import disconnect_ib


def main() -> None:
    print("Running read-only strategy chat (requires Gateway + configured provider)...")
    agent = get_strategy_agent(allow_staging=False)
    result = agent.run(
        (
            "Read the configured account summary and positions. Summarize the "
            "largest visible risks without staging or submitting an order."
        ),
    )

    print(f"\nModel: {result.model}")
    print(f"Iterations: {result.iterations}")
    print(f"Finish: {result.finish_reason}")
    print(f"Tool calls ({len(result.tool_traces)}):")
    for t in result.tool_traces:
        print(f"  - {t.name}({t.arguments})")
    print("\n--- Assistant reply ---")
    print(result.content)
    print("\nSmoke test PASSED — agent tool loop completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nSmoke test FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
    finally:
        disconnect_ib()
