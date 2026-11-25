import datetime
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oe import backtest as B          # noqa: E402
from oe import indicators as ind      # noqa: E402
from oe import options as O           # noqa: E402
from oe.data import Bar               # noqa: E402


def weekdays(a, b):
    d, out = a, set()
    while d <= b:
        if d.weekday() < 5:
            out.add(d)
        d += datetime.timedelta(days=1)
    return out


class Options(unittest.TestCase):
    def test_put_call_parity(self):
        S, K, T, v = 25458.55, 25450, 3 / 365, 0.1643
        c, p = O.price(S, K, T, v, "CE"), O.price(S, K, T, v, "PE")
        self.assertAlmostEqual(c - p, S - K * math.exp(-O.RATE * T), places=6)
        self.assertAlmostEqual(c, 163.0, delta=1.5)           # the estimate quoted to the user

    def test_expired_option_is_intrinsic(self):
        self.assertEqual(O.price(25500, 25450, 0, 0.15, "CE"), 50)
        self.assertEqual(O.price(25500, 25450, 0, 0.15, "PE"), 0)

    def test_charges(self):
        # buy Rs 10,000, sell Rs 12,000: 40 + STT 18 + NSE 7.82 + SEBI 0.02 + GST 8.61 + stamp 0.30
        self.assertAlmostEqual(O.charges(10000, 12000), 74.75, places=2)

    def test_weekly_expiry_calendar(self):
        known = weekdays(datetime.date(2025, 8, 1), datetime.date(2025, 9, 30))
        last = datetime.date(2025, 9, 30)
        self.assertEqual(O.next_expiry(datetime.date(2025, 8, 26), known, last), datetime.date(2025, 8, 28))  # Thu
        self.assertEqual(O.next_expiry(datetime.date(2025, 8, 28), known, last), datetime.date(2025, 9, 2))   # Tue
        future = set()
        last26 = datetime.date(2026, 11, 19)
        # 24 Nov 2026 is an NSE holiday: that week's expiry moves to Monday 23 Nov
        self.assertEqual(O.next_expiry(datetime.date(2026, 11, 19), future, last26 - datetime.timedelta(days=30)),
                         datetime.date(2026, 11, 23))
        # on Monday 23 Nov itself that is expiry day: no expiry-day trade, so the next week's
        self.assertEqual(O.next_expiry(datetime.date(2026, 11, 23), future, last26 - datetime.timedelta(days=30)),
                         datetime.date(2026, 12, 1))

    def test_sensex_calendar_charges_and_lot(self):
        known = weekdays(datetime.date(2024, 11, 1), datetime.date(2025, 12, 31))
        last = datetime.date(2025, 12, 31)
        self.assertEqual(O.next_expiry(datetime.date(2024, 12, 2), known, last, "SENSEX").weekday(), 4)   # Friday
        self.assertEqual(O.next_expiry(datetime.date(2025, 3, 3), known, last, "SENSEX").weekday(), 1)    # Tuesday
        self.assertEqual(O.next_expiry(datetime.date(2025, 10, 6), known, last, "SENSEX").weekday(), 3)   # Thursday
        self.assertLess(O.charges(10000, 12000, "SENSEX"), O.charges(10000, 12000, "NIFTY"))  # BSE fee is lower
        self.assertEqual(O.lot_for("SENSEX", datetime.date(2026, 12, 17)), 20)
        self.assertEqual(O.lot_for("SENSEX", datetime.date(2027, 1, 7)), 25)
        strike, prem = O.choose_strike(82850, 3 / 365, 0.163, "CE", 1500, 0.20, 15000, 0.5, "SENSEX", 20)
        self.assertEqual(strike % 100, 0)

    def test_strike_steps_out_of_the_money_to_fit_the_risk(self):
        S, T, v = 25458.55, 5 / 365, 0.1643
        strike, prem = O.choose_strike(S, T, v, "CE", 1500, 0.20, 15000, 0.5)
        self.assertGreater(strike, 25450)                       # ATM (Rs 211 x 65 x 20% = Rs 2,743) does not fit
        self.assertLessEqual(prem * O.LOT * 0.20, 1500)
        self.assertIsNone(O.choose_strike(S, T, v, "CE", 10, 0.20, 15000, 0.5))


class Indicators(unittest.TestCase):
    def bars(self, closes):
        t = datetime.datetime(2026, 1, 5, 9, 15)
        return [Bar(t + datetime.timedelta(hours=k), c, c + 1, c - 1, c) for k, c in enumerate(closes)]

    def test_basics(self):
        self.assertEqual(ind.ema([5.0] * 10, 3)[-1], 5.0)
        self.assertEqual(ind.rsi([float(x) for x in range(30)])[-1], 100.0)
        up = self.bars([100.0 + k for k in range(40)])
        self.assertEqual(ind.supertrend(up)[-1], 1)
        self.assertEqual(ind.psar(up)[-1], 1)
        hi, lo = ind.donchian_prev(up, 20)
        self.assertIsNone(hi[19])
        self.assertEqual(hi[20], max(b.h for b in up[:20]))


class StopFirst(unittest.TestCase):
    def test_a_bar_that_touches_both_counts_as_the_stop(self):
        class Ctx(object):
            minutes = 60
        t = datetime.datetime(2026, 11, 17, 9, 15)
        closes = [25400, 25450, 25450]
        bars = [Bar(t, 25400, 25420, 25380, 25400), Bar(t + datetime.timedelta(hours=1), 25400, 25460, 25390, 25450),
                Bar(t + datetime.timedelta(hours=2), 25450, 25900, 25000, 25450)]
        ctx = Ctx()
        ctx.bars, ctx.c, ctx.vix_prev = bars, closes, [15.0] * 3
        known = weekdays(datetime.date(2026, 11, 1), datetime.date(2026, 11, 30))
        cfg = dict(B.DEFAULTS, max_loss=100000.0)
        trades, skipped, ruin = B.simulate(ctx, {1: 2}, {t.date(): (1, 1)}, cfg, known, datetime.date(2026, 11, 30))
        self.assertEqual(trades[0]["reason"], "stop")
        self.assertLess(trades[0]["net"], 0)


if __name__ == "__main__":
    unittest.main()
