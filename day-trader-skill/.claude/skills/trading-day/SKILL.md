---
name: trading-day
description: >-
  Runs and reports the user's one-month paper-trading test, end to end, from 2026-11-20 to about
  2026-12-18: Indian stocks with a Rs 15,000 practice account (day-trader-skill's opening-range
  breakout rules, run by the stock autopilot) and NIFTY / SENSEX options with a Rs 15,000 paper
  account (options-ensemble's Algorithm B, with Donchian breakout as a shadow book). Use when the
  user says "start my trading day", "run today's trades", "status", "how did today go", "today's
  report", "score", "the month so far", or asks about the paper month. Paper only.
argument-hint: "[run | status | report | score]"
---

# trading-day

One month of paper trading, two accounts, run by the clock. Claude's job is to make sure the day
runs, to explain what happened in plain words, and to keep the test honest. Nothing here can place
a real order: stocks end in `practice.py` and options in `paper.py`, both paper ledgers.

`${CLAUDE_SKILL_DIR}` is this folder. The stock project is the repository that holds it; the
options project is the `options-ensemble` folder next to it.

```bash
python "${CLAUDE_SKILL_DIR}/run_day.py" run       # both accounts, now to the end of the day
python "${CLAUDE_SKILL_DIR}/run_day.py" status    # what is open, what happened so far today
python "${CLAUDE_SKILL_DIR}/run_day.py" report    # the day's report -> trader/reports/YYYY-MM-DD.md
python "${CLAUDE_SKILL_DIR}/run_day.py" score     # the month so far, both accounts
```

## What runs each trading day (India time)

| time | stocks (Rs 15,000) | options (Rs 15,000) |
| --- | --- | --- |
| 9:10 | the scheduled task "PaperTradingDay" starts `run_day.py run` | same |
| 9:35 to 14:30 | every 5 minutes: 48 liquid NSE stocks scanned for a FRESH opening-range breakout; skip a breakout under 0.15 %, a price too high for 2 shares under the Rs 11,250 cap, news tagged earnings / legal / deal / halt / risk, a Time Machine "strongly toward the stop"; the best Time Machine lean is sized (max loss Rs 150) and must pass trader-risk; then the practice entry | at 10:15, 11:15, 12:15, 13:15, 14:15: Algorithm B (the 5 indicators that called direction best on all past days, 4 of 5 must agree) on NIFTY and SENSEX; one lot of the stronger signal, the strike nearest the money whose loss at the stop fits Rs 1,500 |
| until the exit | stop at the opening-range midpoint, target 1R, settled from real bars | premium -20 % stop, +40 % target, checked on 5-minute bars |
| 15:05 / 15:15 | stocks out by 15:05 | options out by 15:15 |
| after | a skip is logged on a day without a trade; `trader/reports/<date>.md` | the Donchian shadow book runs the same way, for comparison |

At most one stock trade and one options trade a day. Both stop themselves after the close.

## Steps

1. **"Start my trading day" / `run`.** Check the date: weekends, 2026-11-24 and 2026-12-25 are
   closed. Check whether today's run is already going (`trader/state/stocks_run.log` and the
   options `paper/log.txt` have lines from today). If the scheduled task did not start it (the
   computer was off or asleep), start `run_day.py run` in the background and say that decision
   points already passed are logged as missed, never traded late.
2. **During the day / `status`.** Read the status out plainly: what was bought, at what price, the
   stop and target, or why nothing was bought yet (the stocks passed over are listed with reasons).
3. **After the close / `report`.** Run `run_day.py report` and explain the day in a few sentences:
   each account's trade and result after charges, the shadow book next to Algorithm B, the month
   so far. Losses are said as plainly as wins.
4. **The month's end (about 2026-12-18) / `score`.** Read both scoreboards together: trades, win
   rate, average win against average loss, net after charges, the deepest drop, days missed.
   Compare Algorithm B with its Donchian shadow. Remind the user that about 20 trades is a small
   sample, and that option prices here were estimates.

## Rules that keep the test honest

- Paper only. Never place, draft or suggest a real order from this skill, and never switch either
  account to real money. Going live is the user's decision after the month, in their own config.
- No rule changes during the month. If the user wants a change, write it down for the next month.
- Never record a trade with hindsight. A day the run did not happen is a missed day, not a trade
  picked afterwards from the chart.
- Report every day, including days with no trade and days with losses.
- SENSEX prices on Yahoo run about 15 minutes late; its signals are acted on late, and the report
  says so when a SENSEX trade is taken.

## Files

| file | what |
| --- | --- |
| `trader/config.json` | stock rules: budget 15000, max loss 150 a trade, cap 11250, `"paper": true`, `"auto_paper": true` |
| `trader/journal.json` | the stock practice month (practice.py) |
| `trader/state/autopilot.json`, `autopilot.log` | what the stock autopilot looked at and why it passed |
| `../options-ensemble/paper/ledger.json`, `log.txt` | the options paper month, both books |
| `trader/reports/<date>.md` | the day's report |

To stop the month early: `schtasks /Delete /TN PaperTradingDay /F` (the files stay).

Education and tooling, not financial advice. Paper results, especially on estimated option prices,
are not a promise of real ones.

## Stock swing shadow book (from 2026-11-26)

`swing.py` keeps a separate Rs 15,000 paper account (`trader/swing/journal.json`) that copies the stock autopilot's entries (same stock, time, price, shares and stop; one position at a time) but targets 2R and may hold overnight for up to 3 trading days, out by 15:05 on the third. It settles from real 5-minute bars after each day (`run_day.py run` calls `swing.py update`; gaps below the stop fill at the open; delivery charges when held overnight). It appears in the daily report, `status` and `score`. Report it next to the main stock account, never in place of it.

## US paper month: the original repo (from 2026-11-25)

A separate folder, `C:\Users\welcome\OneDrive\Documents\trading\day-trader-us`, holds the original day-trader-skill code exported unchanged from git commit 3d0f4ef (no India changes), plus `autopilot/us_auto.py` (the clock and a paper fill simulator). `setup_server.ps1` in this skill registers its daily 19:45 IST run together with the India run.
- **Budget:** Rs 15,000 = $162.66 at 92.22 INR/USD. The original limits are scaled by percentage: $1.63 max loss a trade, $4.88 a day, $130.13 an order, 3 trades a day, whole shares.
- **Method:** the original defaults. The morning `scan.py daily` builds the watchlist, then `scan.py orb`, news, `exit.py plan` (stop at the range midpoint, target 2R, out 15:55 New York), Time Machine, size and risk.
- **Hours:** 19:30 to 02:30 IST.
- **Commands:** `python autopilot/us_auto.py status | report | score`, run in that folder.
- **Files:** journal at `trader/journal.json`, reports at `trader/reports/<date>.md`.

`run_day.py score` includes it. Paper only.
