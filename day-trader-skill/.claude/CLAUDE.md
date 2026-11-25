# Paper-trading month: handoff (read this first)

This folder is part of the user's one-month **paper** trading test. Nothing ever goes to a broker.

The test runs from 2026-11-20 to about 2026-12-18 for India, and to 2026-12-25 for the US. It was built and run on the user's laptop, then on 2026-11-25 moved to a server reached with Jump Desktop, which is on every day. The laptop's schedule was deleted, so only one machine runs.

## The five paper books

| Book | Where | Money | Method |
|---|---|---|---|
| India stocks (main) | `day-trader-skill` (India mode, `trader/`) | Rs 15,000 | ORB autopilot on 48 NSE stocks, target 1R, out 15:05 IST |
| India swing shadow | `day-trader-skill/trader/swing/` | Rs 15,000 from 2026-11-26 | copies the main entries; target 2R; holds up to 3 trading days |
| Options, Algorithm B | `options-ensemble` (`paper/ledger.json`) | Rs 15,000 | NIFTY/SENSEX; best 5 of 19 indicators, 4 of 5 must agree; hourly 10:15-14:15; -20%/+40%; out 15:15 |
| Options, Donchian shadow | `options-ensemble` | Rs 15,000 | Donchian breakout, the same exits |
| US, original repo | `day-trader-us` | Rs 15,000 = $162.66 | the original day-trader-skill code, unchanged (git 3d0f4ef); ORB, 2R, out 15:55 New York; local fill simulator |

The details live in `.claude/skills/trading-day/SKILL.md`, `day-trader-us/autopilot/README.md` and `options-ensemble/README.md`.

The three folders must sit side by side in one `trading` folder: the code finds them by relative path.

## Daily schedule (India time)

- **09:10:** `python .claude/skills/trading-day/run_day.py run`. It runs India stocks and options side by side, plus the swing book, then writes `trader/reports/<date>.md`.
- **19:45:** `python day-trader-us/autopilot/us_auto.py run`. It runs the US day, then writes `day-trader-us/trader/reports/<date>.md`.

The code skips weekends and holidays. India: 2026-12-25. US: 2026-11-26 Thanksgiving, 2026-11-27 closes at 13:00 New York, 2026-12-25.

## Setting up on the new machine

1. Get the folder, keeping it outside OneDrive:
   - **From GitHub:** `git clone https://github.com/BENNYameen/trader.git C:\trading`. It is a private repo, so sign in when Git asks. Cloning into `C:\trading` gives the right layout.
   - **Or unzip** `trading-move-*.zip` into `C:\trading`.
2. Install Python 3.8 or newer from python.org and tick "Add to PATH". It uses the standard library only; no pip packages are needed.
3. Register both daily runs. In PowerShell, as Administrator if possible, run `powershell -ExecutionPolicy Bypass -File .claude\skills\trading-day\setup_server.ps1`. It converts the India times to the server's time zone. Claude may be blocked from registering tasks; if so, the user runs it.
   - **On a Linux server, use cron instead.** Run the two commands under "Daily schedule" at 09:10 and 19:45 India time, converted to the server's zone (`date` shows it). Run each from its own folder with `python3`. The tasks may fire every day: the code skips closed days.
4. Run `python .claude/skills/trading-day/move_to_server.py check`. Every line should be OK.
5. Copy `../claude-context/memory/*.md` into your own auto-memory folder; they hold what earlier sessions learned.
   - `../claude-context/chat-history.md` is a cleaned, readable copy of the whole earlier chat (19-25 Nov), with email addresses removed. Search it for the history behind a decision.
   - The raw chat files (`claude-context/chat/*.jsonl`) are in the zip only, never on GitHub.
6. Missed sessions:
   - The laptop's US run for 2026-11-25 was stopped at 17:27 IST for the move. If it is still before 19:30 IST on 2026-11-25, start the US run by hand. Otherwise 25 Nov simply was not run, and the US month starts on 2026-11-27.
   - India's next run is 2026-11-26 at 09:10 IST.

## Commands the user says, and what to run

- **"start":** `run_day.py run` in the background (India). For the US at night: `us_auto.py run` in `day-trader-us`.
- **"status" / "how is it going":** `run_day.py status`, plus `us_auto.py status`.
- **"how did today go" / "report":** `run_day.py report`, plus `us_auto.py report`.
- **"score" / "the month so far":** `run_day.py score`, which covers all five books.

## Hard rules (from the user and earlier sessions)

- **Paper only.** Never place real orders or automate real money.
  - Zerodha's hosted Kite MCP is read-only except GTT orders.
  - `.claude/settings.local.json` denies the order tools.
  - Zerodha has no paper account.
- Never ask for, or put, API keys in chat.
- NSE's site blocks scripts. Do not spoof headers; the user downloads `EQUITY_L.csv` by hand if needed.
- No hindsight trades. Missed decision points are logged as missed.
- Change rules only when the user asks, and log the date so results before and after are compared separately.
- Report losses plainly. A month is a small sample. SEBI, FY26: 87.7% of individual F&O traders lost money.

## Rule-change log

- **2026-11-23, about 13:50 IST:** India stocks went from 1 trade a day to no count limit (`max_trades_per_day: 0`). The autopilot holds one position at a time, does not re-buy a stock the same day, and keeps the Rs 450 daily risk cap.
- **2026-11-25:** added the India swing shadow book, starting 2026-11-26.
- **2026-11-25:** added the US original-repo test, Rs 15,000 = $162.66 at 92.22 INR/USD.

## Known caveats

- **Stop fills are slightly optimistic.** Stops fill at the stop price unless a bar opens beyond it. A real stop order in a fast drop can fill worse; for example, DAR in a 24 Nov test bar fell to $48.30, below its $50.10 stop.
- **Option prices are estimates.** They are Black-Scholes values from India VIX, not real quotes. SENSEX on Yahoo is about 15 minutes late.
- **Expect few US trades.** At $162.66 with whole shares, most breakouts are refused: one share must cost under about $122 and risk under $1.63. Few trades is the honest result, not a bug.
- **Data-centre IPs can hit Yahoo rate limits.** `move_to_server.py check` tests access.

## Results at the 2026-11-25 close (run `run_day.py score` for live numbers)

| Book | Balance |
|---|---|
| India stocks | Rs 15,070.58 (3 trades: 2 wins, 1 loss) |
| Swing | Rs 15,000 (starts 26 Nov) |
| Options, Algorithm B | Rs 16,255.64 (1 win, 1 loss) |
| Options, Donchian | Rs 17,642.67 (1 win) |
| US | $162.66 (no trades yet) |

## About the user

- The user is learning trading.
- They like plain, simple words, short answers and small tables.
- Their messages are short: "start", "status", "how is it going", "3-ok".
- Use they/them.

Open offer, not accepted: a 5-minute Algorithm B shadow book for options.
