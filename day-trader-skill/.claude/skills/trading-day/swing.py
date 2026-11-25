#!/usr/bin/env python3
"""Swing shadow book for the stock side: a separate Rs 15,000 paper account that copies the stock
autopilot's entries but exits differently. Paper only; it never touches the main practice journal.

Rules (fixed for the month):
  entry   the same stock, time, price, share count and stop as an autopilot trade, when this book has
          no open position and the cash covers it (one position at a time)
  target  2R: entry + 2 x (entry - stop), rounded up to the NSE tick
  hold    overnight allowed, up to 3 trading days counting the entry day; out by flat_by (15:05) on
          the 3rd day if neither the stop nor the target was hit
  fills   from real 5-minute bars, stop before target; a day that opens below the stop fills at the
          open (gap risk); charges: Zerodha intraday if closed the same day, delivery (CNC) otherwise

    python swing.py update [--home DIR]   # copy new entries and settle, from the bars (run after the day)
    python swing.py score  [--home DIR]
    python swing.py reset --start YYYY-MM-DD [--cash 15000] [--home DIR]"""

import datetime
import importlib.util
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("TRADER_MARKET", "in")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HOLIDAYS = {"2026-11-24", "2026-12-25", "2027-01-26"}
MAX_DAYS = 3
SESSION_END = datetime.time(15, 15)       # Yahoo's NSE bars after this are patchy (closing auction)


def _practice():
    spec = importlib.util.spec_from_file_location("practice", str(REPO / "trader-broker" / "practice.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _practice()


def now_ist():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0) + \
        datetime.timedelta(hours=5, minutes=30)


def read(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def nse_tick(price):
    for top, tick in ((250, 0.01), (1000, 0.05), (5000, 0.10), (10000, 0.50), (20000, 1.00)):
        if price < top:
            return tick
    return 5.00


def up_to_tick(x):
    t = nse_tick(x)
    return round(math.ceil(round(x / t, 6)) * t, 2)


def trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def last_hold_day(d):
    n, cur = 1, d
    while n < MAX_DAYS:
        cur += datetime.timedelta(days=1)
        if trading_day(cur):
            n += 1
    return cur


def delivery_charges(buy, sell):
    """Zerodha equity delivery (CNC): no brokerage, STT 0.1% both sides, DP charge on the sell."""
    stt = 0.001 * (buy + sell)
    txn = 0.0000307 * (buy + sell)
    sebi = 0.000001 * (buy + sell)
    stamp = 0.00015 * buy
    dp = 15.93                                 # Rs 13.50 + GST, once per sell
    return round(stt + txn + sebi + 0.18 * (txn + sebi) + stamp + dp, 2)


def bars_for(sym, day, today, now_utc, cache):
    key = (sym, day)
    if key not in cache:
        bars, _ = P.day_bars(P.chart_text(sym, day, today), sym, day, now_utc)
        cache[key] = [b for b in bars if b[0].time() < SESSION_END]
    return cache[key]


def settle(p, until, now_utc, cache):
    """Walk p from its entry to `until` (local datetime). -> (reason, exit day, HH:MM, price) or None."""
    day = datetime.date.fromisoformat(p["date"])
    last = datetime.date.fromisoformat(p["last_day"])
    while day <= min(last, until.date()):
        if trading_day(day):
            bars = [b for b in bars_for(p["symbol"], day, until.date(), now_utc, cache)
                    if b[0] + P.STEP <= until]
            entry_at = datetime.datetime.combine(day, P.hhmm(p["entry_at"])) if day.isoformat() == p["date"] \
                else datetime.datetime.combine(day, datetime.time(0, 0))
            final = day == last
            flat_by = p["flat_by"] if final else "23:59"
            day_over = final and until >= datetime.datetime.combine(day, P.hhmm(p["flat_by"]))
            r = P.walk(bars, entry_at, p["stop"], p["target"], flat_by, day_over)
            if r:
                reason, at, price = r
                return ("time" if reason == "flat" else reason), day.isoformat(), at, price
        day += datetime.timedelta(days=1)
    return None


def close(book, p, result):
    reason, day, at, price = result
    buy, sell = p["entry"] * p["qty"], price * p["qty"]
    cost = P.charges(buy, sell) if day == p["date"] else delivery_charges(buy, sell)
    gross = round(sell - buy, 2)
    net = round(gross - cost, 2)
    risk = (p["entry"] - p["stop"]) * p["qty"]
    p.update({"status": "closed", "reason": reason, "exit": price, "exit_date": day, "exit_at": at,
              "gross": gross, "charges": cost, "net": net, "r": round(gross / risk, 2) if risk else None})
    book["cash"] = round(book["cash"] + sell - cost, 2)


def cmd_update(home):
    trader = home / "trader"
    book_path = trader / "swing" / "journal.json"
    book = read(book_path)
    if book is None:
        print("No swing book yet: swing.py reset --start YYYY-MM-DD")
        return 1
    main = read(trader / "journal.json", {}) or {}
    now = now_ist()
    now_utc = now - datetime.timedelta(hours=5, minutes=30)
    cache, msgs = {}, []
    seen = set(book.setdefault("seen", []))
    entries = sorted((t for t in main.get("trades", []) if t["date"] >= book["start"] and t["id"] not in seen),
                     key=lambda t: (t["date"], t["entry_at"]))
    for m in entries:
        at = datetime.datetime.combine(datetime.date.fromisoformat(m["date"]), P.hhmm(m["entry_at"]))
        if at > now:
            continue
        for p in [x for x in book["trades"] if x["status"] == "open"]:
            r = settle(p, at, now_utc, cache)
            if r:
                close(book, p, r)
                msgs.append(say_close(p))
        seen.add(m["id"])
        if any(x["status"] == "open" for x in book["trades"]):
            msgs.append("%s %s %s: not copied, the swing book is still holding a position" %
                        (m["date"], m["entry_at"], m["symbol"]))
            continue
        cost = m["entry"] * m["qty"]
        if cost > book["cash"]:
            msgs.append("%s %s: not copied, Rs %.2f is more than the cash" % (m["date"], m["symbol"], cost))
            continue
        risk = m["entry"] - m["stop"]
        p = {"id": "swing-%s" % m["id"], "from": m["id"], "date": m["date"], "symbol": m["symbol"],
             "qty": int(m["qty"]) if float(m["qty"]).is_integer() else m["qty"], "entry": m["entry"], "entry_at": m["entry_at"], "stop": m["stop"],
             "target": up_to_tick(m["entry"] + 2 * risk), "flat_by": m.get("flat_by", "15:05"),
             "last_day": last_hold_day(datetime.date.fromisoformat(m["date"])).isoformat(), "status": "open"}
        book["trades"].append(p)
        book["cash"] = round(book["cash"] - cost, 2)
        msgs.append("BUY %s %s at Rs %.2f (%s %s), stop Rs %.2f, target Rs %.2f (2R), hold until %s at most"
                    % (p["qty"], p["symbol"], p["entry"], p["date"], p["entry_at"], p["stop"], p["target"],
                       p["last_day"]))
    for p in [x for x in book["trades"] if x["status"] == "open"]:
        r = settle(p, now, now_utc, cache)
        if r:
            close(book, p, r)
            msgs.append(say_close(p))
    book["seen"] = sorted(seen)
    write(book_path, book)
    for line in msgs:
        print(line)
    if not msgs:
        print("Swing book: nothing new.")
    return 0


def say_close(p):
    word = {"stop": "STOP", "target": "TARGET", "time": "3-day limit"}[p["reason"]]
    return "SELL %s %s at Rs %.2f (%s, %s %s): net Rs %+.2f after Rs %.2f charges (%+.2fR)" % (
        p["qty"], p["symbol"], p["exit"], word, p["exit_date"], p["exit_at"], p["net"], p["charges"], p["r"] or 0)


def lines_for(home, day):
    book = read(home / "trader" / "swing" / "journal.json") or {}
    out = []
    for p in book.get("trades", []):
        if p["date"] == day or p.get("exit_date") == day or p["status"] == "open":
            line = "- %s %s at Rs %.2f (%s %s), stop Rs %.2f, target Rs %.2f" % (
                p["qty"], p["symbol"], p["entry"], p["date"], p["entry_at"], p["stop"], p["target"])
            if p["status"] == "closed":
                line += "; out at Rs %.2f (%s, %s %s): net Rs %+.2f after Rs %.2f charges" % (
                    p["exit"], {"stop": "stop", "target": "target", "time": "3-day limit"}[p["reason"]],
                    p["exit_date"], p["exit_at"], p["net"], p["charges"])
            else:
                line += "; holding (until %s at most)" % p["last_day"]
            out.append(line)
    return out or ["- Nothing bought or sold today."]


def cmd_score(home):
    book = read(home / "trader" / "swing" / "journal.json")
    if book is None:
        print("No swing book yet.")
        return 1
    closed = [p for p in book["trades"] if p["status"] == "closed"]
    opened = [p for p in book["trades"] if p["status"] == "open"]
    wins = [p for p in closed if p["net"] > 0]
    net = sum(p["net"] for p in closed)
    held = sum(p["entry"] * p["qty"] for p in opened)
    print("Stock swing shadow book from %s, Rs %s. Same entries as the autopilot; target 2R; hold up to "
          "%d trading days. Paper only." % (book["start"], "{:,.2f}".format(book["start_cash"]), MAX_DAYS))
    if closed:
        print("Trades closed: %d. Wins %d, losses %d (win rate %d%%). Net Rs %+.2f after Rs %.2f charges."
              % (len(closed), len(wins), len(closed) - len(wins), round(100.0 * len(wins) / len(closed)), net,
                 sum(p["charges"] for p in closed)))
    else:
        print("No closed trades yet.")
    for p in opened:
        print("Holding %s %s from %s at Rs %.2f (stop Rs %.2f, target Rs %.2f, out by %s)"
              % (p["qty"], p["symbol"], p["date"], p["entry"], p["stop"], p["target"], p["last_day"]))
    print("Cash Rs %s%s." % ("{:,.2f}".format(book["cash"]),
                             (" + Rs %s in a position at cost" % "{:,.2f}".format(held)) if held else ""))
    return 0


def cmd_reset(home, start, cash):
    path = home / "trader" / "swing" / "journal.json"
    old = read(path)
    if old and old.get("trades"):
        print("%s already holds trades; not wiping it." % path)
        return 1
    write(path, {"start": start, "start_cash": cash, "cash": cash, "trades": [], "seen": [],
                 "rules": __doc__.split("Rules (fixed for the month):")[1].split("\n\n")[0].strip()})
    print("Swing shadow book ready: Rs %s from %s." % ("{:,.2f}".format(cash), start))
    return 0


def main(argv=None):
    args = list(argv or sys.argv[1:]) or ["score"]
    home = Path(args[args.index("--home") + 1]) if "--home" in args else REPO
    if args[0] == "update":
        return cmd_update(home)
    if args[0] == "score":
        return cmd_score(home)
    if args[0] == "reset" and "--start" in args:
        cash = float(args[args.index("--cash") + 1]) if "--cash" in args else 15000.0
        return cmd_reset(home, args[args.index("--start") + 1], cash)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
