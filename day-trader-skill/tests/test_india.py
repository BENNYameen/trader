"""India mode ("market": "in"): NSE session in IST, NSE holidays, .NS tickers,
rupee limits, NSE price ticks and Zerodha tickets. Every tool is loaded a
second time with the market pinned to "in"; the US tests load the default."""

import datetime
import io
import json
import os
import random
import shutil
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal

from _load import load, FIX

entry = load("trader-entry", "entry", market="in")
scan = load("trader-scanner", "scan", market="in")
ex = load("trader-exit", "exit", market="in")
tm = load("trader-timemachine", "timemachine", market="in")
risk = load("trader-risk", "check", market="in")
size = load("trader-budget", "size", market="in")
ticket = load("trader-broker", "ticket", market="in")
alerts = load("trader-alerts", "alerts", market="in")
news = load("trader-news", "news", market="in")
facts = load("trader-analyst", "facts", market="in")
ptr = load("trader-pelosi", "ptr", market="in")
entry_us = load("trader-entry", "entry")

DIR = os.path.join(FIX, "trader-india")
DAY = datetime.date(2026, 11, 19)                 # a Thursday, a trading day
HOLIDAY = datetime.date(2026, 11, 24)             # Prakash Gurpurb Sri Guru Nanak Dev
CFG = {"market": "in", "budget": 2000, "cash_buffer_pct": 10, "max_position_pct": 75,
       "max_order_inr": 1500, "min_order_inr": 100, "max_loss_per_trade_inr": 20,
       "max_daily_loss_inr": 60, "max_trades_per_day": 3, "min_reward_risk": 1.0, "require_stop": True,
       "no_entries_before": "09:30", "no_entries_after": "14:30", "flat_by": "15:05",
       "broker": "zerodha", "product": "CNC", "paper": True}
ORDER = {"symbol": "RELIANCE", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day",
         "order_class": "bracket", "take_profit_limit_price": "1375.1", "stop_loss_stop_price": "1360.9",
         "plan": {"entry": 1368.0, "stop": 1360.9, "target": 1375.1, "flat_by": "15:05"}}


def quiet(fn, *a):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(*a)
    return code, out.getvalue(), err.getvalue()


class Clock(unittest.TestCase):
    def test_every_tool_is_in_india_mode(self):
        for mod in (entry, scan, ex, tm, risk, size, ticket, alerts, news):
            self.assertEqual(mod.MARKET, "in", mod.__name__)
        self.assertEqual(entry_us.MARKET, "us")
        self.assertTrue(facts.INDIA and ptr.INDIA)

    def test_ist_is_utc_plus_5_30_all_year(self):
        for month in (1, 7, 11):
            utc = datetime.datetime(2026, month, 5, 4, 30)
            self.assertEqual(entry.to_eastern(utc), datetime.datetime(2026, month, 5, 10, 0))
        self.assertEqual(entry.parse_now("2026-11-19 10:00"), datetime.datetime(2026, 11, 19, 4, 30))
        self.assertEqual(entry.parse_now("2026-11-19 10:00 IST"), datetime.datetime(2026, 11, 19, 4, 30))

    def test_the_session_is_9_15_to_15_15(self):
        for mod in (entry, scan, alerts):
            self.assertEqual(mod.session(DAY), (datetime.time(9, 15), datetime.time(15, 15)), mod.__name__)
        self.assertEqual((tm.OPEN_MIN, tm.CLOSE_MIN, tm.SESSION_BARS), (555, 915, 72))

    def test_nse_holidays_and_weekends(self):
        self.assertEqual(entry.trading_day(HOLIDAY), (False, "NSE holiday: Prakash Gurpurb Sri Guru Nanak Dev"))
        self.assertEqual(scan.trading_day(datetime.date(2026, 11, 21))[0], False)      # Saturday
        self.assertIsNone(ex.session(datetime.date(2026, 12, 25)))                     # Christmas
        self.assertIsNotNone(ex.session(datetime.date(2026, 11, 26)))                  # US Thanksgiving: open

    def test_india_defaults(self):
        self.assertEqual(entry.DEFAULTS, {"no_entries_before": "09:30", "no_entries_after": "14:30"})
        self.assertEqual(ex.DEFAULTS["flat_by"], "15:05")
        self.assertEqual((alerts.FLAT_BY, ticket.FLAT_BY, scan.NO_ENTRIES_AFTER), ("15:05", "15:05", "14:30"))

    def test_the_report_speaks_ist_nse_and_rupees(self):
        buf = io.StringIO()
        entry._IndiaText(buf).write("10:15 ET: NYSE, New York time, $1,366.70")
        self.assertEqual(buf.getvalue(), "10:15 IST: NSE, India time, Rs 1,366.70")
        buf = io.StringIO()
        entry._IndiaText(buf).write("ETF RETAIL")   # whole words only
        self.assertEqual(buf.getvalue(), "ETF RETAIL")
        buf = io.StringIO()
        entry._IndiaText(buf).write("Flat by 15:05 New York, at 2026-11-19 09:45 New York.")
        self.assertEqual(buf.getvalue(), "Flat by 15:05 IST, at 2026-11-19 09:45 IST.")


class Tickers(unittest.TestCase):
    def test_yahoo_ticker_ends_in_ns(self):
        self.assertEqual(entry.yahoo_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(scan.to_yahoo("BAJAJ-AUTO"), "BAJAJ-AUTO.NS")
        self.assertEqual(scan.from_yahoo("BAJAJ-AUTO.NS"), "BAJAJ-AUTO")
        self.assertEqual(tm.yahoo_ticker("IRFC.NS"), "IRFC.NS")
        self.assertEqual(entry_us.yahoo_symbol("BRK.B"), "BRK-B")

    def test_an_ampersand_is_quoted_in_the_url(self):
        self.assertEqual(entry.chart_path("M&M", "1d", "5m"), "/v8/finance/chart/M%26M.NS?range=1d&interval=5m")
        self.assertIn("symbols=M%26M.NS,RELIANCE.NS&", scan.spark_path(["M&M", "RELIANCE"], "3mo", "1d"))
        self.assertIn("/M%26M.NS?", alerts.yahoo_url("M&M"))
        self.assertIn("/M%26M.NS?", tm.chart_url("M&M"))
        self.assertEqual(news.yahoo_symbol("M&M"), "M%26M.NS")

    def test_spark_maps_back_to_nse_tickers(self):
        doc = {"spark": {"result": [{"symbol": "M&M.NS", "response": [
            {"meta": {"symbol": "M&M.NS"}, "timestamp": [1], "indicators": {"quote": [{"close": [3200.0]}]}}]}]}}
        self.assertEqual(list(scan.parse_spark(doc)), ["M&M"])

    def test_risk_knows_nse_tickers_and_blocks_fno(self):
        for sym in ("RELIANCE", "M&M", "BAJAJ-AUTO", "20MICRONS", "BAJFINANCE"):
            self.assertTrue(risk.TICKER.match(sym), sym)
        for sym in ("NIFTY26NOVFUT", "RELIANCE26NOV1400CE", "BANKNIFTY2611352000PE"):
            self.assertTrue(risk.DERIVATIVE.match(sym), sym)
        for sym in ("RELIANCE", "20MICRONS", "SPICE"):
            self.assertFalse(risk.DERIVATIVE.match(sym), sym)


class Universe(unittest.TestCase):
    def test_eq_series_only(self):
        with open(os.path.join(DIR, "EQUITY_L.csv"), encoding="utf-8") as fh:
            kept, counts = scan.build_nse_universe(fh.read())
        self.assertEqual([s for s, _ in kept], ["20MICRONS", "BAJAJ-AUTO", "IRFC", "M&M", "RELIANCE"])
        self.assertEqual(dict(kept)["M&M"], "Mahindra & Mahindra Limited")
        self.assertEqual((counts["BE series"], counts["BZ series"], counts["rows"]), (1, 1, 7))

    def test_universe_command_reads_the_saved_file(self):
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "universe.txt")
            code, text, _ = quiet(scan.main, ["universe", "--offline", DIR, "--out", out])
            self.assertEqual(code, 0)
            self.assertIn("Kept 5 EQ-series shares", text)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(fh.readline(), "20MICRONS|20 Microns Limited\n")
            code, _, err = quiet(scan.main, ["universe", "--offline", tmp, "--out", out])
            self.assertEqual(code, 1)
            self.assertIn("open https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv in your browser", err)
        finally:
            shutil.rmtree(tmp)


class Ticks(unittest.TestCase):
    def test_nse_price_bands(self):
        for price, tick in ((99.5, "0.01"), (249.99, "0.01"), (250, "0.05"), (999, "0.05"), (1366.7, "0.10"),
                            (5000, "0.50"), (12000, "1.00"), (130000, "5.00")):
            self.assertEqual(ex.nse_tick(price), Decimal(tick), price)
            self.assertAlmostEqual(ticket.nse_tick(price), float(tick), msg=price)

    def test_the_stop_goes_down_to_a_tick_and_the_target_up(self):
        p = ex.compute(1368.00, "or_mid", None, "r", Decimal("1"), or_high=1366.70, or_low=1355.20)
        self.assertEqual(p["stop"], Decimal("1360.90"))          # (1366.70 + 1355.20) / 2 = 1360.95, down to 0.10
        self.assertIn("rounded down to the $0.10 tick", p["stop_detail"])
        self.assertEqual(p["target"], Decimal("1375.10"))
        p = ex.compute(300.15, "price", Decimal("298.33"), "r", Decimal("1.5"))
        self.assertEqual(p["stop"], Decimal("298.30"))           # 0.05 tick under Rs 1,000
        self.assertEqual(p["target"], Decimal("302.95"))         # 302.925 up to the tick: never under 1.5R
        self.assertGreaterEqual(p["reward_risk"], Decimal("1.5"))


class TimeMachine(unittest.TestCase):
    """Synthetic NSE data shaped like Yahoo's: 72 bars from 9:15 to 15:10 plus a stray 15:25 print."""

    @staticmethod
    def chart(days, today_bars, seed=7):
        rng = random.Random(seed)
        stamps, o, h, lo, c = [], [], [], [], []
        price = 1000.0

        def bar(d, minute):
            nonlocal price
            ist = datetime.datetime.combine(d, datetime.time(9, 15)) + datetime.timedelta(minutes=minute)
            stamps.append(int((ist - datetime.timedelta(hours=5, minutes=30)
                               - datetime.datetime(1970, 1, 1)).total_seconds()))
            op = price
            price = round(price * (1 + rng.gauss(0, 0.002)), 2)
            o.append(op)
            c.append(price)
            h.append(round(max(op, price) * 1.001, 2))
            lo.append(round(min(op, price) * 0.999, 2))

        for d in days:
            for k in range(72):
                bar(d, 5 * k)
            bar(d, 370)                                           # 15:25, outside the 72-bar session
        for k in range(today_bars):
            bar(DAY, 5 * k)
        doc = {"chart": {"result": [{"meta": {"symbol": "DEMO.NS", "dataGranularity": "5m",
                                              "regularMarketTime": stamps[-1] + 300},
                                     "timestamp": stamps,
                                     "indicators": {"quote": [{"open": o, "high": h, "low": lo, "close": c,
                                                               "volume": [1000] * len(c)}]}}],
                         "error": None}}
        return doc, c

    def test_a_replay_on_nse_bars(self):
        days, d = [], DAY
        while len(days) < 25:
            d -= datetime.timedelta(days=1)
            if d.weekday() < 5 and d.isoformat() not in tm_holidays():
                days.append(d)
        doc, closes = self.chart(sorted(days), today_bars=5)
        e = closes[-2]                                            # bar 3 of today (9:30 to 9:35), its close
        raw = {"symbol": "DEMO", "side": "buy", "date": DAY.isoformat(), "setup": "orb", "entry": e,
               "entry_time": "9:35 AM", "interval": "5m", "stop": round(e * 0.99, 2),
               "target": round(e * 1.01, 2), "stop_rule": "pct", "opening_range": {"minutes": 15}}
        plan = tm.normalize_plan(raw)
        self.assertEqual(plan["entry_bar"], 3)
        res = tm.time_machine(json.dumps(doc), plan, tm.parse_now("2026-11-19 09:45"), replays=400, seed=3)
        mc = res["mc"]
        self.assertEqual(mc["pool_sessions"], 25)                 # every day kept: 72 bars, 15:25 dropped
        self.assertAlmostEqual(mc["p_target"] + mc["p_stop"] + mc["p_neither"], 1.0, places=6)
        self.assertEqual(mc["until"], "15:15")
        self.assertEqual(mc["band_times"][0], "09:35")


def tm_holidays():
    return entry.NYSE_HOLIDAYS


class Rules(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 19, 4, 30)                  # 10:00 IST

    def test_inr_keys_fill_the_limits(self):
        self.assertEqual(risk.money_keys({"max_loss_per_trade_inr": 20})["max_loss_per_trade_usd"], 20)
        res = risk.check([ORDER], CFG, today=DAY.isoformat(), now=self.NOW)
        self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])
        tight = dict(CFG, max_loss_per_trade_inr=5)
        res = risk.check([ORDER], tight, today=DAY.isoformat(), now=self.NOW)
        self.assertEqual(res["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any("max loss" in r for r in res["results"][0]["reasons"]))

    def test_the_entry_window_in_ist(self):
        late = datetime.datetime(2026, 11, 19, 9, 15)             # 14:45 IST, after no_entries_after 14:30
        res = risk.check([ORDER], CFG, today=DAY.isoformat(), now=late)
        self.assertTrue(any("no new entries after 14:30" in r for r in res["results"][0]["reasons"]))
        hol = datetime.datetime(2026, 11, 24, 4, 30)
        res = risk.check([ORDER], CFG, today="2026-11-24", now=hol)
        self.assertTrue(any("NSE holiday" in r for r in res["results"][0]["reasons"]))

    def test_futures_and_options_are_blocked(self):
        fut = dict(ORDER, symbol="NIFTY26NOVFUT")
        res = risk.check([fut], CFG, today=DAY.isoformat(), now=self.NOW)
        self.assertTrue(any("NSE future or option" in r for r in res["results"][0]["reasons"]))

    def test_a_2000_rupee_account_buys_one_reliance_share(self):
        plan = {"symbol": "RELIANCE", "side": "buy", "date": DAY.isoformat(), "entry": 1368.0,
                "stop": 1360.9, "target": 1375.1, "setup": "orb", "flat_by": "15:05"}
        s = size.size_trade(plan, dict(CFG, fractional=True), today=DAY.isoformat())
        self.assertEqual(s["qty"], 1)                             # Rs 1,500 max order: one share at Rs 1,368
        self.assertEqual(s["max_loss_per_trade_usd"], 20)


class Zerodha(unittest.TestCase):
    def test_a_bracket_becomes_entry_then_sl_m(self):
        ko = ticket.kite_orders(ORDER, CFG)
        self.assertEqual(ko[0], {"exchange": "NSE", "tradingsymbol": "RELIANCE", "transaction_type": "BUY",
                                 "quantity": 1, "product": "CNC", "order_type": "MARKET", "validity": "DAY"})
        self.assertEqual(ko[1]["order_type"], "SL-M")
        self.assertEqual((ko[1]["transaction_type"], ko[1]["trigger_price"]), ("SELL", 1360.9))
        self.assertEqual(len(ko), 2)                              # the target is an alert, not a second sell

    def test_the_ticket(self):
        text, ready = ticket.render(ORDER, 1, 1, CFG, None, {"orders": []}, DAY.isoformat())
        self.assertFalse(ready)                                   # no risk check yet
        self.assertIn("PRACTICE (paper): do not place it in Kite, Zerodha", text)
        self.assertIn("1. BUY NSE RELIANCE: qty 1, product CNC, MARKET, validity DAY", text)
        self.assertIn("SL-M, trigger 1360.90", text)
        self.assertIn("Flat by 15:05", text)
        self.assertNotIn("place_stock_order", text)
        live = dict(CFG, paper=False)
        text, _ = ticket.render(ORDER, 1, 1, live, None, {"orders": []}, DAY.isoformat())
        self.assertIn("LIVE ACCOUNT, REAL MONEY, Zerodha", text)

    def test_off_tick_prices_are_flagged(self):
        self.assertFalse(ticket.off_tick(1360.9))
        self.assertTrue(ticket.off_tick(1360.95))
        self.assertFalse(ticket.off_tick(300.15))
        self.assertTrue(ticket.off_tick(300.17))
        bad = dict(ORDER, stop_loss_stop_price="1360.95")
        text, _ = ticket.render(bad, 1, 1, CFG, None, {"orders": []}, DAY.isoformat())
        self.assertIn("CHECK: 1360.95 is off NSE's tick", text)

    def test_json_ticket_has_kite_fields_and_no_tool(self):
        t = ticket.ticket_json(ORDER, 1, CFG, None, {"orders": []}, DAY.isoformat())
        self.assertIsNone(t["tool"])
        self.assertEqual(t["kite_orders"][0]["tradingsymbol"], "RELIANCE")

    def test_ist_offset_in_the_log(self):
        self.assertEqual(ticket.ny_iso(datetime.datetime(2026, 11, 19, 4, 45)), "2026-11-19T10:15:00+05:30")


class Alerts(unittest.TestCase):
    def test_the_clock(self):
        st = alerts.market_status(datetime.datetime(2026, 11, 19, 4, 30))
        self.assertTrue(st["open"])
        self.assertEqual((st["opens"], st["closes"]), ("09:15", "15:15"))
        st = alerts.market_status(datetime.datetime(2026, 11, 24, 4, 30))
        self.assertFalse(st["open"])
        self.assertEqual(st["next_open"], "2026-11-25 09:15")

    def test_plan_alerts_flatten_by_15_05(self):
        rules = alerts.rules_from_plan({"symbol": "RELIANCE", "stop": 1360.9, "target": 1375.1})
        self.assertEqual([r["at"] for r in rules if r["type"] == "time"], ["15:05"])


class News(unittest.TestCase):
    def test_the_google_news_query(self):
        q = news.news_query("RELIANCE", "Reliance Industries Limited", 48)
        self.assertEqual(urllib.parse.unquote_plus(q), '"Reliance Industries" when:2d')
        self.assertEqual(urllib.parse.unquote_plus(news.news_query("IRFC", None, 12)), "IRFC NSE when:1d")

    def test_google_news_items_carry_the_publisher(self):
        xml = (b'<rss><channel><item><title>Reliance shares rise 2% - The Economic Times</title>'
               b'<link>https://news.google.com/rss/articles/x</link><guid>x1</guid>'
               b'<pubDate>Thu, 19 Nov 2026 04:00:00 GMT</pubDate><description>&lt;a&gt;</description>'
               b'<source url="https://economictimes.indiatimes.com">The Economic Times</source>'
               b'</item></channel></rss>')
        it = news.parse_rss(xml, "RELIANCE", "Google News", publisher=True)[0]
        self.assertEqual((it["title"], it["source"], it["summary"]),
                         ("Reliance shares rise 2%", "The Economic Times", ""))
        self.assertEqual(news.TZ, "IST")


class UsOnly(unittest.TestCase):
    def test_sec_and_house_tools_say_so(self):
        code, _, err = quiet(facts.main, [])
        self.assertEqual(code, 2)
        self.assertIn("SEC EDGAR, which covers US-listed companies only", err)
        code, _, err = quiet(ptr.main, [])
        self.assertEqual(code, 2)
        self.assertIn("US House", err)


if __name__ == "__main__":
    unittest.main()
