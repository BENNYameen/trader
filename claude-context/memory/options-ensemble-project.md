---
name: options-ensemble-project
description: "Separate NIFTY/SENSEX options research and paper-trading project; backtest favoured breakouts and \"best 5 on past data\"; live paper trader built"
metadata:
  node_type: memory
  type: project
  originSessionId: 14016a46-58dd-4c5e-b397-b98990a3d0c9
  modified: 2026-11-19T10:03:06.734Z
---

The options project lives at `C:\Users\welcome\OneDrive\Documents\trading\options-ensemble`, separate from day-trader-skill. It is standard-library Python and paper only.

Backtest (2026-11-19: hourly bars, walk-forward, test Nov 2024 to Nov 2026, against 200 random-direction runs):
- On NIFTY, Algorithm B (the best 5 of 19 indicators on past data, 4 of 5 agree) made +31k, Donchian +24k and Bollinger breakout +16k.
- On SENSEX (lot 20, strikes 100 apart, Thursday expiry since Sep 2025), Algorithm B made +30k, Donchian +33k and Bollinger +35k.
- On NIFTY, most other methods wiped out the Rs 15,000.
- No method had a high win rate: 42-49%, with average wins larger than average losses.

The live paper trader is `paper.py run|tick|replay|score|day`, with its logic in `oe/live.py`.
- Algorithm B trades the Rs 15,000 account and Donchian keeps a shadow book.
- Decisions at 10:15 to 14:15 hourly, at most one trade a day, NIFTY or SENSEX by signal strength.
- Exit at -20% or +40% of the premium, or at 15:15.
- Prices are Black-Scholes estimates from India VIX.
- SENSEX data on Yahoo is about 15 minutes late.
- The ledger is `paper/ledger.json`, reset for 2026-11-20.

**Why:** the user asked for an ensemble of methods running concurrently, trading only when they agree strongly.

**How to apply:** never automate real-money orders. Keep the multiple-testing caveat and SEBI's FY26 figure (87.7% of individual F&O traders lost money) in view when results come in. The daily run is the trading-day skill ([[practice-month]]).
