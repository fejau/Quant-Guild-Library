# Felix IBKR AI Trader

Account-specific fork of the Quant Guild AI stock trading terminal. It connects
to the same localhost-only IBKR Client Portal Gateway used by the Fable project.
IBKR credentials never enter this application.

## Safety model

The default mode is **read-only**:

- portfolio, balances, positions, orders, market snapshots, and history can be read;
- the AI can research and maintain theses;
- no order-submission tool is available to the AI;
- automation performs research only;
- no broker order endpoint is called.

Trading can be armed later in `paper` or `live` mode. Even when armed, the AI
can only stage an immutable order proposal. A person must approve that exact
proposal from the local UI before the server submits it to IBKR.

## Existing Fable gateway

The local `.env` points at:

```text
/Users/felixjauvin/Fable/.env
```

Only `GATEWAY_URL` and `IBKR_ACCOUNT_ID` are imported from that file. Local
settings override shared values. The account id is never copied into Git. If
Fable leaves the id blank, readonly mode uses the account currently selected by
the authenticated Gateway session. Paper/live submission still requires an
explicit `IBKR_ACCOUNT_ID` so trading can never follow an accidental selection.

Start or authenticate the existing gateway using the Fable workflow, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python app.py
```

Open `http://127.0.0.1:5050`.

## Modes

### Read-only

```dotenv
IBKR_TRADING_MODE=readonly
IBKR_LIVE_TRADING_ENABLED=false
```

### Paper trading

Paper mode requires an explicitly configured paper account, normally an account
id beginning with `DU`:

```dotenv
IBKR_TRADING_MODE=paper
IBKR_PAPER_TRADING_ENABLED=true
IBKR_ALLOWED_SYMBOLS=SPY,AAPL
```

### Live trading

Live mode is fail-closed and requires every gate below:

```dotenv
IBKR_TRADING_MODE=live
IBKR_LIVE_TRADING_ENABLED=true
IBKR_LIVE_TRADING_CONFIRM=I_UNDERSTAND_LIVE_IBKR_RISK
IBKR_ALLOWED_SYMBOLS=SPY,AAPL
IBKR_MAX_ORDER_NOTIONAL=500
IBKR_MAX_POSITION_PCT=0.05
IBKR_ALLOW_SHORTING=false
IBKR_REQUIRE_LIMIT_ORDERS=true
```

Restart the app after changing modes. A live-ready status does not submit
anything by itself; every order still requires a separate UI approval.

## Hard controls

- Explicit configured account must match an account returned by the gateway.
- Non-local gateway URLs are rejected.
- Empty symbol allowlist blocks all staged orders in trading modes.
- New orders require a broker conid.
- SELL quantity cannot exceed the long position unless shorting is explicitly enabled.
- Maximum notional (in the security's quote currency) and post-trade position
  percentage (converted to the account base currency) are checked server-side.
- Limit orders can be required.
- Staged orders expire and are immutable.
- Broker warning replies are never auto-confirmed.
- Runtime portfolio/trade data is atomically written and excluded from Git.
