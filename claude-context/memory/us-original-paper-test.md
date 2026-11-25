---
name: us-original-paper-test
description: "Parallel US paper month running the ORIGINAL day-trader-skill code unchanged, in a separate day-trader-us folder, Rs 15,000 = $162.66"
metadata:
  node_type: memory
  type: project
  originSessionId: 14016a46-58dd-4c5e-b397-b98990a3d0c9
  modified: 2026-11-25T11:39:49.663Z
---

On 2026-11-25 the user asked for a separate folder to test the original repo's own method on US stocks with Rs 15,000, in parallel with the India tests, for a month. On budget currency they chose Rs 15,000 converted (about $170, not $15,000); on fills they chose the local simulator over an Alpaca paper account.

- **Folder:** `C:\Users\welcome\OneDrive\Documents\trading\day-trader-us`. It is a `git archive` of commit 3d0f4ef, unchanged. The only additions are in `autopilot/`: `us_auto.py`, which runs the clock, the pipeline and a simulator that fills from real Yahoo 5-minute bars, and `setup_schedule_us.ps1` for weekdays at 19:45 IST.
- **Config:** `trader/config.json` has budget 162.66 (at 92.22 INR/USD) and the original limits scaled by percentage: $1.63 a trade, $4.88 a day, $130.13 max order, 3 trades a day, whole shares (`fractional: false`).
- **Original defaults kept:** stop at the opening-range midpoint, target 2R, flat by 15:55 New York.
- **Autopilot filters:** the same filters as the India autopilot.

**Why:** the user wants to compare "our" India methods with the repo's original task, side by side.

**How to apply:** paper only, and never touch the original code in that folder. US hours are 19:30 to 02:30 IST, and the PC must stay awake. At this budget most breakouts get refused, because one share's risk to the range midpoint exceeds $1.63 or one share costs more than about $122. Few trades is the honest result, not a bug. Compare it with [[practice-month]] at month end, and note the small sample.
