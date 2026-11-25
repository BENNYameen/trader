"""The practice account (trader-broker/practice.py), India mode, on synthetic 5-minute bars."""

import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import load

pr = load("trader-broker", "practice", market="in")

DAY = "2026-11-19"
CFG = {"market": "in", "budget": 5000, "max_loss_per_trade_inr": 50, "max_daily_loss_inr": 150,
       "max_order_inr": 3750, "max_trades_per_day": 1, "no_entries_before": "09:30", "no_entries_after": "14:30",
       "flat_by": "15:05", "broker": "zerodha", "product": "CNC", "paper": True}
ORDER = {"symbol": "DEMO", "side": "buy", "qty": "3", "type": "market", "time_in_force": "day",
         "order_class": "bracket", "take_profit_limit_price": "915.45", "stop_loss_stop_price": "888.55",
         "plan": {"entry": 902.0, "stop": 888.55, "target": 915.45, "flat_by": "15:05"}}
PLAN = {"symbol": "DEMO", "date": DAY, "entry": 902.0, "stop": 888.55, "target": 915.45, "flat_by": "15:05"}


def chart(special, flat=903.0):
    """A day of 5-minute bars from 9:15 to 15:25 IST; `special` maps HH:MM -> (o, h, l, c)."""
    stamps, o, h, lo, c = [], [], [], [], []
    t = datetime.datetime(2026, 11, 19, 9, 15)
    while t.time() <= datetime.time(15, 25):
        bar = special.get(t.strftime("%H:%M"), (flat, flat + 0.5, flat - 0.5, flat))
        utc = t - datetime.timedelta(hours=5, minutes=30)
        stamps.append(int((utc - datetime.datetime(1970, 1, 1)).total_seconds()))
        for arr, v in zip((o, h, lo, c), bar):
            arr.append(v)
        t += datetime.timedelta(minutes=5)
    return {"chart": {"result": [{"meta": {"symbol": "DEMO.NS", "regularMarketTime": stamps[-1] + 300},
                                  "timestamp": stamps,
                                  "indicators": {"quote": [{"open": o, "high": h, "low": lo, "close": c,
                                                            "volume": [1000] * len(c)}]}}]}}


def quiet(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pr.main(argv)
    return code, out.getvalue(), err.getvalue()


class Practice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = {k: os.path.join(self.tmp, f) for k, f in (
            ("journal", "journal.json"), ("portfolio", "portfolio.json"), ("state", "broker.json"),
            ("config", "config.json"), ("orders", "orders.json"), ("plan", "plan.json"), ("chart", "DEMO.json"))}
        self.write("config", CFG)
        self.write("orders", {"orders": [ORDER]})
        self.write("plan", PLAN)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, key, doc):
        with open(self.p[key], "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

    def read(self, key):
        with open(self.p[key], encoding="utf-8") as fh:
            return json.load(fh)

    def files(self, *keys):
        out = []
        for k in ("journal", "portfolio", "state", "config") + keys:
            out += ["--" + k, self.p[k]]
        return out

    def approve(self):
        fp = pr.T.fingerprint(ORDER)
        self.write("state", {"orders": [{"at": DAY + "T09:40:30+05:30", "date": DAY, "index": 1, "fingerprint": fp,
                                         "symbol": "DEMO", "side": "buy", "status": "approved", "reply": "yes"}]})

    def opened(self, special, now="2026-11-19 09:41"):
        self.write("chart", chart(special))
        self.assertEqual(quiet(["reset", "--cash", "5000"] + self.files() + ["--now", now])[0], 0)
        self.approve()
        code, out, err = quiet(["open"] + self.files("orders", "plan") + ["--offline", self.p["chart"],
                                                                          "--now", now])
        self.assertEqual(code, 0, err)
        return out

    def settle(self, now="2026-11-19 15:10"):
        code, out, err = quiet(["settle"] + self.files() + ["--offline", self.p["chart"], "--now", now])
        self.assertEqual(code, 0, err)
        return out

    def test_charges_estimate(self):
        self.assertAlmostEqual(pr.charges(3500, 3500), 3.72, places=2)     # about Rs 3.72 a round trip
        # Rs 1 lakh each way: brokerage capped at Rs 20 a side (40), STT 25, NSE 6.14, SEBI 0.20,
        # GST 18% of 46.34 = 8.34, stamp 3: Rs 82.68
        self.assertAlmostEqual(pr.charges(100000, 100000), 82.68, places=2)

    def test_open_needs_your_yes(self):
        self.write("chart", chart({}))
        quiet(["reset", "--cash", "5000"] + self.files())
        code, _, err = quiet(["open"] + self.files("orders", "plan") + ["--offline", self.p["chart"],
                                                                        "--now", "2026-11-19 09:41"])
        self.assertEqual(code, 1)
        self.assertIn("no yes recorded today", err)

    def test_open_books_the_buy_at_the_last_closed_bar(self):
        out = self.opened({"09:35": (901.0, 902.6, 900.8, 902.4)})
        self.assertIn("Practice buy: 3 DEMO at 902.40 (09:41)", out)
        self.assertIn("Rs ", out)                                          # India mode speaks rupees
        t = self.read("journal")["trades"][0]
        self.assertEqual((t["entry"], t["entry_at"], t["status"], t["max_loss"]), (902.4, "09:41", "open", 41.55))
        self.assertAlmostEqual(self.read("portfolio")["cash"], 5000 - 3 * 902.4, places=2)
        st = [r["status"] for r in self.read("state")["orders"]]
        self.assertEqual(st, ["approved", "placed", "filled"])

    def test_target(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4), "10:30": (910.0, 916.0, 909.0, 914.0)})
        out = self.settle()
        self.assertIn("TARGET hit, 10:35 at 915.45", out)
        t = self.read("journal")["trades"][0]
        self.assertEqual((t["reason"], t["exit"], t["gross"]), ("target", 915.45, 39.15))
        self.assertAlmostEqual(t["net"], 39.15 - pr.charges(3 * 902.4, 3 * 915.45), places=2)
        pf = self.read("portfolio")
        self.assertEqual(pf["positions"], [])
        self.assertAlmostEqual(pf["cash"], 5000 + t["net"], places=2)

    def test_a_gap_through_the_stop_fills_at_the_open(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4), "10:00": (885.0, 886.0, 884.0, 885.5)})
        self.settle()
        t = self.read("journal")["trades"][0]
        self.assertEqual((t["reason"], t["exit"], t["exit_at"]), ("stop", 885.0, "10:05"))

    def test_a_bar_that_touches_both_is_the_stop(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4), "11:00": (903.0, 916.0, 888.0, 905.0)})
        self.settle()
        t = self.read("journal")["trades"][0]
        self.assertEqual((t["reason"], t["exit"]), ("stop", 888.55))

    def test_the_running_bar_counts_the_stop_not_the_target(self):
        # bought at 09:41 inside the 09:40 bar: its high above the target came before the buy
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4), "09:40": (902.4, 917.0, 901.0, 903.0)})
        self.settle()
        t = self.read("journal")["trades"][0]
        self.assertEqual(t["reason"], "flat")

    def test_flat_by_the_close_of_the_15_00_bar(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4), "15:00": (904.0, 905.5, 903.5, 905.1)})
        out = self.settle()
        self.assertIn("out at the flat-by time, 15:05 at 905.10", out)

    def test_still_open_before_the_flat_by_time(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4)})
        out = self.settle(now="2026-11-19 11:00")
        self.assertIn("DEMO still open", out)
        self.assertEqual(self.read("journal")["trades"][0]["status"], "open")

    def test_auto_needs_both_config_flags(self):
        self.write("chart", chart({"09:35": (901.0, 902.6, 900.8, 902.4)}))
        quiet(["reset", "--cash", "5000"] + self.files())
        base = ["open", "--auto"] + self.files("orders", "plan") + ["--offline", self.p["chart"],
                                                                    "--now", "2026-11-19 09:41"]
        code, _, err = quiet(base)
        self.assertEqual(code, 1)
        self.assertIn("\"auto_paper\": true", err)
        self.write("config", dict(CFG, auto_paper=True))
        code, out, err = quiet(base)
        self.assertEqual(code, 0, err)
        approval = self.read("state")["orders"][0]
        self.assertTrue(approval["auto"])
        self.assertIn("AUTO: standing instruction", approval["reply"])
        self.assertTrue(self.read("journal")["trades"][0]["auto"])

    def test_open_refuses_a_price_that_ran(self):
        self.write("chart", chart({}))
        quiet(["reset", "--cash", "5000"] + self.files())
        self.approve()
        base = ["open"] + self.files("orders", "plan") + ["--now", "2026-11-19 09:41"]
        code, _, err = quiet(base + ["--price", "916"])
        self.assertIn("at or past the target", err)
        code, _, err = quiet(base + ["--price", "910"])                     # 3 x (910 - 888.55) = 64.35 > 50
        self.assertEqual(code, 1)
        self.assertIn("over your Rs 50.00 max loss", err)

    def test_practice_only(self):
        self.write("config", dict(CFG, paper=False))
        code, _, err = quiet(["reset", "--cash", "5000"] + self.files())
        self.assertEqual(code, 1)
        self.assertIn("practice money only", err)

    def test_reset_keeps_recorded_trades(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4)})
        code, _, err = quiet(["reset", "--cash", "5000"] + self.files())
        self.assertEqual(code, 1)
        self.assertIn("already holds 1 trade", err)

    def test_skip_and_score(self):
        self.opened({"09:35": (901.0, 902.6, 900.8, 902.4), "10:30": (910.0, 916.0, 909.0, 914.0)})
        self.settle()
        code, out, _ = quiet(["skip", "--reason", "no setup passed the rules", "--date", "2026-11-20"] + self.files())
        self.assertEqual(code, 0)
        code, _, err = quiet(["skip", "--reason", "x", "--date", DAY] + self.files())
        self.assertIn("already has a practice trade", err)
        code, out, _ = quiet(["score"] + self.files())
        self.assertIn("Days: 1 traded, 1 skipped.", out)
        self.assertIn("Trades closed: 1. Wins 1, losses 0 (win rate 100%).", out)
        s = pr.score(self.read("journal"))
        self.assertAlmostEqual(s["balance"], 5000 + s["net"], places=2)
        self.assertEqual(s["drawdown"], 0.0)


if __name__ == "__main__":
    unittest.main()
