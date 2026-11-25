---
name: practice-month
description: "One-month automatic paper trading test from 2026-11-20 to about 2026-12-18, stocks Rs 15,000 plus NIFTY/SENSEX options Rs 15,000, run by the trading-day skill"
metadata:
  node_type: memory
  type: project
  originSessionId: 14016a46-58dd-4c5e-b397-b98990a3d0c9
  modified: 2026-11-25T11:58:29.512Z
---

The user is running a one-month paper test, 2026-11-20 to about 2026-12-18; 2026-11-24 and 2026-12-25 are NSE holidays. The user asked that Claude make the entries and exits daily, so both sides run automatically on paper.

**Stocks:** Rs 15,000. `trader/config.json` has budget 15000, max loss 150 a trade, 450 a day, max order 11,250, `"paper": true` and `"auto_paper": true`. The rules are ORB on 48 liquid NSE stocks, entering only fresh breakouts. Skip a breakout under 0.15%, a price too high for 2 shares, red-flag news tags, or a Time Machine verdict of "strongly toward the stop". Pick the best Time Machine lean, then the risk check, then `practice.py open --auto`, and settle from bars, out by 15:05. Ledger: `trader/journal.json`.

**Rule change, 2026-11-23 about 13:50 IST, at the user's request ("dont limit it, try more"):** stocks went from 1 trade a day to no count limit (`"max_trades_per_day": 0`). The autopilot holds one position at a time, does not re-buy a stock already traded that day, and stops when the risk check's Rs 450 daily loss limit blocks an entry. That limit sums each entry's max loss at its stop, wins included. Compare stock results before and after this date separately.

**Options:** Rs 15,000, run by `options-ensemble/paper.py` ([[options-ensemble-project]]).

**Runner:** the project skill `.claude/skills/trading-day` (`run_day.py run|status|report|score`) runs both side by side and writes `trader/reports/<date>.md`. On 2026-11-19 the auto-mode classifier blocked Claude from registering the Windows task. The user must run `setup_schedule.ps1` themselves, or start each day with "start my trading day" (Claude then starts `run_day.py run` in the background).

**Moved to a server, 2026-11-25:** the user moved all runs to an always-on server reached with Jump Desktop, where they use Claude Code. The laptop's PaperTradingDay task was deleted and its US run stopped, so nothing runs on the laptop. The package is `move_to_server.py pack`, a zip next to the `trading` folder. The server setup is `setup_server.ps1`, which registers both tasks with India times converted to the server's zone, then `move_to_server.py check`. The handoff for the server's Claude is `day-trader-skill/.claude/CLAUDE.md`. If the user is on the laptop again, the laptop copy is a stale backup: ask before running anything here.

**Why:** the user wants an honest month-long test of both systems before any real money.

**How to apply:** keep it paper only. No rule changes mid-month unless the user asks (then log the date), and no hindsight trades; missed decision points are logged as missed. Report losses plainly. Review both scoreboards at the month's end, and warn that about 20 trades is a small sample.

**Swing shadow book, added 2026-11-25 at the user's request (they asked whether stocks could make Rs 300/day, holding overnight if needed; they chose a shadow book over raising risk):** `.claude/skills/trading-day/swing.py`, ledger `trader/swing/journal.json`, Rs 15,000 from 2026-11-26. Same entries as the autopilot, target 2R, hold up to 3 trading days. A pre-start test on 23–25 Nov trades: HCLTECH reached 1R, then hit the stop before 2R (−Rs 86 in the swing book vs +Rs 69 in the main book). Compare it with the main stock book at month end.
