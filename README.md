# trading: paper-trading month (private)

Three folders that must stay side by side:

- `day-trader-skill`: Indian stocks (the India mode of day-trader-skill), plus the `trading-day` runner, the swing shadow book and the dashboard.
- `options-ensemble`: the NIFTY / SENSEX options paper trader (Algorithm B, with a Donchian shadow book).
- `day-trader-us`: the original day-trader-skill code (MIT, by Jake Schincariol), unchanged, plus `autopilot/` for the US paper test.

The paper-month data (journals, ledgers, configs, reports) is included, so another machine can carry on from here.

Paper only. Nothing here sends orders to any broker.

## Run it on a server (Windows)

1. Clone this repo to `C:\trading`, outside OneDrive.
2. Install Python 3 from python.org.
3. In PowerShell, as Administrator if you can, run `day-trader-skill\.claude\skills\trading-day\setup_server.ps1`.
4. Run `python day-trader-skill\.claude\skills\trading-day\move_to_server.py check`.

The details for Claude Code are in `day-trader-skill/.claude/CLAUDE.md`.
