# US paper month: the original repo, run as is

Everything outside this `autopilot/` folder is the original day-trader-skill code (git commit
3d0f4ef, "The Trader skill v2"), exported unchanged with `git archive`, so no India changes. This
folder adds only the clock and a paper simulator:

- `us_auto.py`: runs the original pipeline every trading day and books the fills on paper.
- Scheduling: `day-trader-skill/.claude/skills/trading-day/setup_server.ps1` registers this run (19:45 IST daily) together with the India run, on any Windows machine that is on every day.

- **Budget:** Rs 15,000 = **$162.66** (92.22 INR/USD on 2026-11-25). The original example limits are scaled
  by the same percentages: max loss 1% a trade ($1.63), 3% a day ($4.88), at most $130.13 an order,
  3 trades a day, whole shares only.
- **Method (original defaults):**
  - A morning `scan.py daily` builds the watchlist.
  - `scan.py orb` finds 15-minute opening-range breakouts on it.
  - `news.py` and `exit.py plan` follow: stop at the range midpoint, **target 2R**, out by 15:55 New York.
  - Then `timemachine.py`, `size.py` and `check.py`.
- **Autopilot choices (fixed):** fresh breakouts only (10 min), at least 0.15%, no red-flag news,
  not "strongly toward the stop", best Time Machine lean, one position at a time.
- **Hours:** 09:00 to 16:00 New York = **19:30 to 02:30 IST** (US standard time). The PC must stay awake.
- **Files:** `trader/journal.json` (trades), `trader/reports/<date>.md` (the day), `trader/state/us_autopilot.log`.

Commands: `python autopilot/us_auto.py run | status | report | score`.

Paper only. Nothing goes to Alpaca or any broker. The original's live path needs your typed yes for every order.
