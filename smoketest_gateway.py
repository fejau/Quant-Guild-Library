"""Safe connectivity check. This script never calls an order endpoint."""

from __future__ import annotations

from config import trading_mode_status
from ib_bridge import get_account_summary, get_gateway, get_open_orders, get_positions


def main() -> None:
    gateway = get_gateway(fresh=True)
    print("Trading mode:", trading_mode_status())
    print("Session:", gateway.session())
    summary = get_account_summary()
    positions = get_positions()
    orders = get_open_orders()
    print("Account summary readable:", summary.get("ok"))
    print("Position count:", len(positions.get("positions") or []))
    print("Open-order count:", len(orders.get("open_orders") or []))


if __name__ == "__main__":
    main()
