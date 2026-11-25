# options-ensemble

A research project, kept apart from `day-trader-skill`: 19 indicators and a small learning
model vote on NIFTY's direction, three algorithms combine the votes, and every one of them
buys same-day NIFTY options **on paper**. Nothing here connects to a broker or places an order.

```bash
python run_backtest.py                  # hourly bars, about 3 years: ~1 year to learn, ~2 years to test
python run_backtest.py --interval 5m    # 5-minute bars, the last 60 days (short)
python run_backtest.py --stop 0.30 --target 0.60 --seeds 100
python -m unittest discover -s tests
```

Standard library only (Python 3.8+). Data: Yahoo's free chart endpoint (`^NSEI`, `^INDIAVIX`),
cached in `data/`. Results go to `results/`.

## The rules of the test

- Rs 15,000 of paper capital, one NIFTY lot (65) per trade, at most one trade a day.
- Decisions at the close of each hourly bar from 10:15 to 14:15 (every 5 minutes from 9:30 to
  14:30 with `--interval 5m`). Calls when the signal says up, puts when it says down.
- Strike: at the money if the loss at the stop fits Rs 1,500, else the nearest cheaper strike
  that does. Nearest weekly expiry with at least one day left (no expiry-day trades). Weekly
  expiry was Thursday until 28 Aug 2025 and Tuesday since; a holiday moves it a day earlier.
- Exit: premium down 20 % (stop), up 40 % (target), or 15:15, whichever comes first. A bar that
  touches both counts as the stop; a gap through the stop fills at the gap.
- Option prices are Black-Scholes estimates with yesterday's India VIX as the volatility. Costs:
  Zerodha's option charges (Rs 20 an order, STT 0.15 % of the sell premium, NSE 0.03553 %, SEBI,
  GST, stamp) plus Rs 0.50 a unit of slippage each side.

## How cheating is kept out

- Indicators use past bars only; the VIX is yesterday's close.
- The learning model, the stacked model and Algorithm B's indicator ranking are refit every 20
  trading days **on the days before**, then judged on the next 20 (walk-forward).
- All settings were fixed before the test. The first ~230 days are used only for learning.
- Every result is compared with 200 runs that buy a random direction each day: a method is only
  interesting if it beats most of them, after costs.

## Results (run on 2026-11-19; test 27 Nov 2024 to 18 Nov 2026, 488 sessions)

| method | trades | win % | net Rs | beats random |
| --- | --- | --- | --- | --- |
| Algorithm B: the best 5 indicators on past data, 4 of 5 must agree | 158 | 44.9 | +31,428 | 96 % |
| Donchian breakout (close beyond the last 20 hours' high or low) | 228 | 42.5 | +23,792 | 95 % |
| Bollinger breakout | 162 | 42.0 | +16,011 | 92 % |
| The other 20 (EMA, SMA, MACD, Supertrend, RSI, ADX, CCI, Stochastic, Williams %R, Heikin-Ashi, Parabolic SAR, opening range, session average, rate of change, both reversion rules, the learning model, majority vote, stacked probability) | | | all lost the Rs 15,000 | |

Checks on the three survivors:

- **Both years positive** for Algorithm B (+23,773 / +7,656) and Donchian (+13,820 / +9,972).
  Algorithm B's equity never fell below the starting Rs 15,000.
- **Other exits**: stop 30 % / target 60 % made all three more (+38k, +43k, +28k); stop 15 % /
  target 30 % kept Algorithm B and Donchian positive and sank Bollinger.
- **A Rs 750 risk cap** (forcing cheaper, further out-of-the-money strikes) sank all three:
  the edge needs options near the money.
- Algorithm B's latest picks: Bollinger breakout, MACD, Donchian breakout, opening range,
  session average. It keeps choosing the breakout family.

SENSEX (one lot of 20, strikes 100 apart, BSE fee 0.0325 %, weekly expiry Friday, then Tuesday
in 2025, Thursday since September 2025), same test years: Algorithm B +30,034, Bollinger breakout
+35,014, Donchian +32,919 (each beat 95 to 96 % of random runs); Algorithm B again chose the
breakout family by itself. SENSEX and NIFTY move together, so this repeats the NIFTY result more
than it independently confirms it.

## Paper trading (the month from 2026-11-20)

```bash
python paper.py reset --cash 15000 --start 2026-11-20   # done
python paper.py run                                     # live: 9:15 to the end of the day, by itself
python paper.py replay --date 2026-11-17                # a past day, as if live, into its own file
python paper.py score
```

Algorithm B trades the Rs 15,000 account and Donchian breakout keeps a shadow book. Each watches
NIFTY and SENSEX at 10:15, 11:15, 12:15, 13:15 and 14:15, takes at most one trade a day (the
stronger signal; a tie goes to NIFTY, whose Yahoo data is live while SENSEX runs about 15 minutes
late), and exits at -20 % / +40 % of the premium or 15:15, checked on 5-minute bars. A decision the
tool sees too late is logged as missed, never traded late. `day-trader-skill/.claude/skills/trading-day`
runs this side by side with the stock autopilot every trading day.

## What this does and does not show

- No method had a high win rate. The survivors win 42 to 49 % of trades and make money because
  the average win (about Rs 1,900) is bigger than the average loss (about Rs 1,200).
- When 23 methods are tested, the best one beats about 96 % of random runs by luck alone. What
  makes the breakout result more than luck is that it repeats: both years, most exit settings,
  and the walk-forward Algorithm B picks the same family by itself.
- Prices are estimates. Real weekly premiums move with demand and the volatility smile, and
  hourly bars miss what happens inside the hour. Drawdowns were deep (Rs 17,000 to 19,000 from a
  peak). SEBI's study for FY26 found 87.7 % of individual F&O traders lost money.
- Next step: Phase 2, paper trading Algorithm B and Donchian side by side, live, with real option
  quotes where available, before any thought of real money.
