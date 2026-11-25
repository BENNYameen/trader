#!/usr/bin/env python3
"""Practice account for trader-broker: a paper ledger that settles each practice
trade from the day's real 5-minute bars. Standard library only. It never places
anything, anywhere: it is for "paper": true.

    python3 practice.py reset --cash 5000      # start a practice month (refuses to wipe recorded trades)
    python3 practice.py open                   # after your yes (ticket.py approve): the practice buy
    python3 practice.py open --price 902.10    # at the price you would have got (default: the live price)
    python3 practice.py settle                 # after the flat-by time: stop, target or flat, from real bars
    python3 practice.py skip --reason "no setup passed the rules"
    python3 practice.py score                  # the scoreboard

open books the buy for the ticket you said yes to: the order must carry your
yes from today in trader/state/broker.json (ticket.py approve). The fill is the
live price (or --price). It refuses when that price is already at the stop or
the target, or when the loss at the stop would break your max loss per trade.

settle walks the bars from the one holding the entry, stop before target:
  a bar that reaches the stop: out at the stop, or at the bar's open when it
    opened below the stop (a gap fills worse)
  a bar that reaches the target: out at the target (in the bar that was already
    running when you got in, only the stop counts)
  a bar that touches both: the stop (the conservative call, as in the Time Machine)
  neither by the flat-by time: out at the close of the bar that ends at flat_by
A trade from today stays open until then unless it hit a side.

Charges in India mode are an estimate at Zerodha's equity intraday rates
(zerodha.com/charges, read 2026-11-19): brokerage 0.03% or Rs 20 an order,
whichever is lower; STT 0.025% on the sell; NSE transaction 0.00307%; SEBI
Rs 10 a crore; GST 18% on brokerage, transaction and SEBI; stamp 0.003% on the
buy. A CNC buy sold the same day is normally charged as intraday: confirm with
Zerodha. US mode counts no charges (commission-free brokers).

Files: trader/journal.json (the month), trader/portfolio.json (cash and shares),
trader/state/broker.json (the log trader-risk reads for the daily limits).
--now pins the clock; --offline reads a saved chart JSON (a file, or a folder of
<SYMBOL>.json) instead of Yahoo.
"""

import argparse
import datetime
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
EPOCH = datetime.datetime(1970, 1, 1)
STEP = datetime.timedelta(minutes=5)


def _ticket():
    """ticket.py from this folder, loaded fresh so it reads the same market as this tool."""
    spec = importlib.util.spec_from_file_location("trader_broker_ticket_for_practice", os.path.join(HERE, "ticket.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = _ticket()
MARKET = T.MARKET


class PracticeError(Exception):
    pass


# ---------------------------------------------------------------- money

def charges(buy_value, sell_value):
    """Estimated Zerodha equity intraday charges for one round trip, in rupees (0 in US mode)."""
    if MARKET != "in":
        return 0.0
    brokerage = min(20.0, 0.0003 * buy_value) + min(20.0, 0.0003 * sell_value)
    stt = 0.00025 * sell_value
    txn = 0.0000307 * (buy_value + sell_value)
    sebi = 0.000001 * (buy_value + sell_value)
    gst = 0.18 * (brokerage + txn + sebi)
    stamp = 0.00003 * buy_value
    return round(brokerage + stt + txn + sebi + gst + stamp, 2)


def limit(cfg, name):
    """A money limit from the config: the _inr key (rupees) or its _usd twin."""
    v = cfg.get(name + "_inr")
    return T._f(v if v is not None else cfg.get(name + "_usd"))


def rs(x):
    return ("-" if x < 0 else "") + "$" + "{:,.2f}".format(abs(x))


def signed(x):
    return ("+" if x >= 0 else "-") + "$" + "{:,.2f}".format(abs(x))


# ---------------------------------------------------------------- files and clock

def read_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise PracticeError("%s is not valid JSON: %s" % (path, e))


def clock(a):
    now = T.parse_now(getattr(a, "now", None))
    return now, T.to_eastern(now)


def hhmm(text):
    h, m = str(text).strip().split(":")
    return datetime.time(int(h), int(m))


# ---------------------------------------------------------------- bars

def yahoo_symbol(sym):
    s = sym.upper()
    if MARKET == "in":
        return s if s.endswith((".NS", ".BO")) else s + ".NS"
    return s.replace(".", "-")


def chart_text(sym, day, today, offline=None):
    if offline:
        path = offline
        if os.path.isdir(offline):
            path = os.path.join(offline, sym.upper() + ".json")
        if not os.path.exists(path):
            raise PracticeError("no offline chart %s" % path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    back = (today - day).days
    if back > 58:
        raise PracticeError("Yahoo keeps 5-minute bars for about 60 days: %s is too far back to settle" % day)
    rng = "1d" if back <= 0 else "5d" if back <= 6 else "1mo" if back <= 28 else "60d"
    last = "no answer"
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=5m" % (
            host, urllib.parse.quote(yahoo_symbol(sym)), rng)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = "HTTP %d" % e.code
            if e.code != 429 and e.code < 500:
                break
            time.sleep(1.0)
        except (urllib.error.URLError, OSError) as e:
            last = str(getattr(e, "reason", e))
    raise PracticeError("Yahoo did not answer for %s (%s): try again in a minute" % (sym, last))


def day_bars(text, sym, day, now_utc, live=False):
    """(bars, price): the complete on-grid 5-minute bars of `day` in local time, each
    (start, open, high, low, close), and the price by now: the last complete bar's
    close, or with live=True the latest price Yahoo shows."""
    try:
        res = json.loads(text)["chart"]["result"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        raise PracticeError("no usable chart for %s" % sym)
    meta = res.get("meta") or {}
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    as_of = now_utc
    rmt = meta.get("regularMarketTime")
    if isinstance(rmt, (int, float)) and EPOCH + datetime.timedelta(seconds=int(rmt)) < as_of:
        as_of = EPOCH + datetime.timedelta(seconds=int(rmt))
    out = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        def at(k):
            arr = q.get(k) or []
            return arr[i] if i < len(arr) else None
        vals = [at(k) for k in ("open", "high", "low", "close")]
        if ts is None or None in vals or int(ts) % 300:
            continue
        start_utc = EPOCH + datetime.timedelta(seconds=int(ts))
        local = T.to_eastern(start_utc)
        if local.date() != day or start_utc + STEP > as_of:
            continue
        out[local] = (local, float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]))
    bars = [out[k] for k in sorted(out)]
    price = bars[-1][4] if bars else None
    if live and isinstance(rmt, (int, float)) and meta.get("regularMarketPrice"):
        if T.to_eastern(EPOCH + datetime.timedelta(seconds=int(rmt))).date() == day:
            price = float(meta["regularMarketPrice"])
    return bars, price


def walk(bars, entry_at, stop, target, flat_by, day_over):
    """-> (reason, exit time HH:MM, exit price), or None while the trade is still open."""
    flat = hhmm(flat_by)
    last = None
    for start, o, h, lo, c in bars:
        end = start + STEP
        if end <= entry_at:
            continue                          # over before the entry
        if start.time() >= flat:
            break
        running = start < entry_at            # this bar began before you were in
        if lo <= stop:
            return "stop", end.strftime("%H:%M"), round(stop if running else min(stop, o), 2)
        if h >= target and not running:
            return "target", end.strftime("%H:%M"), round(target, 2)
        last = (end, c)
    if last and (last[0].time() >= flat or day_over):
        return "flat", last[0].strftime("%H:%M"), round(last[1], 2)
    return None


# ---------------------------------------------------------------- commands

def rules_text(cfg):
    return [
        "Setup: 15-minute opening-range breakout on 5-minute bars; enter on the first close above the range "
        "high, %s to %s." % (cfg.get("no_entries_before", "09:30"), cfg.get("no_entries_after", "14:30")),
        "Stop at the opening-range midpoint; target 1R; out by %s whatever happens." % cfg.get("flat_by", T.FLAT_BY),
        "Risk at most %s a trade and %s a day; at most %s trade(s) a day; at most %s in one stock."
        % (rs(limit(cfg, "max_loss_per_trade") or 0), rs(limit(cfg, "max_daily_loss") or 0),
           cfg.get("max_trades_per_day", 1) or "unlimited", rs(limit(cfg, "max_order") or 0)),
        "Skip a stock: too dear for one share under that cap, a breakout under 0.15%, red-flag news (results, "
        "legal, a deal), or a Time Machine verdict of 'strongly toward the stop'.",
        "Log every trading day: a trade, or a skip with its reason. No rule changes until the month ends.",
    ]


def cmd_reset(a):
    cfg = read_json(a.config, {}) or {}
    if not cfg.get("paper", True):
        raise PracticeError("your config says \"paper\": false; practice.py is for practice money only")
    old = read_json(a.journal, None)
    if old and old.get("trades") and not a.force:
        raise PracticeError("%s already holds %d trade(s). Keep them, or start over with --force (it wipes them)"
                            % (a.journal, len(old["trades"])))
    now, local = clock(a)
    start = a.start or local.date().isoformat()
    doc = {"created_by": "trader-broker practice", "started": start, "start_cash": float(a.cash),
           "currency": "INR" if MARKET == "in" else "USD", "rules": rules_text(cfg), "trades": [], "days": {}}
    T.write_json(a.journal, doc)
    T.write_json(a.portfolio, {"cash": float(a.cash), "positions": []})
    print("Practice account ready: %s of practice money from %s. Nothing goes to any broker." % (rs(a.cash), start))
    print("The rules for the month, fixed now:")
    for i, r in enumerate(doc["rules"], 1):
        print("  %d. %s" % (i, r))
    print("Each day: the pipeline to a ticket, your yes (ticket.py approve), then practice.py open; after %s, "
          "practice.py settle. A day with no trade: practice.py skip --reason \"...\"."
          % cfg.get("flat_by", T.FLAT_BY))
    return 0


def _order_and_plan(a):
    doc = read_json(a.orders, None)
    if not doc:
        raise PracticeError("no orders in %s: run trader-budget (size.py --write) first" % a.orders)
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not 1 <= a.index <= len(orders):
        raise PracticeError("there is no order %d in %s" % (a.index, a.orders))
    order = orders[a.index - 1]
    plan = read_json(a.plan, {}) or {}
    if str(plan.get("symbol", "")).upper() != str(order.get("symbol", "")).upper():
        plan = order.get("plan") or {}
    return order, plan


def cmd_open(a):
    cfg = read_json(a.config, {}) or {}
    if not cfg.get("paper", True):
        raise PracticeError("your config says \"paper\": false: record real fills with ticket.py result, "
                            "not practice.py")
    order, plan = _order_and_plan(a)
    sym = str(order.get("symbol", "")).upper()
    if str(order.get("side", "")).lower() != "buy":
        raise PracticeError("practice.py opens buys; practice.py settle closes them")
    now, local = clock(a)
    today = local.date().isoformat()
    state = T.load_state(a.state)
    fp = T.fingerprint(order)
    if a.auto:
        # the user's standing instruction for a paper month: entries and exits without a yes each time
        if not (cfg.get("paper", True) and cfg.get("auto_paper") is True):
            raise PracticeError("--auto needs \"paper\": true and \"auto_paper\": true in your config")
        state.setdefault("orders", []).append({
            "at": T.ny_iso(now), "date": today, "index": a.index, "fingerprint": fp, "symbol": sym,
            "side": "buy", "plain": T.plain(order), "status": "approved", "auto": True,
            "reply": "AUTO: standing instruction for paper trading (\"auto_paper\": true)"})
        T.write_json(a.state, state)
    rec = T.latest(state, fp, today)
    if not rec or rec.get("status") != "approved":
        raise PracticeError("no yes recorded today for this order (%s): ticket.py show, the user's yes, then "
                            "ticket.py approve --index %d --reply \"...\"" % (T.plain(order), a.index))
    journal = read_json(a.journal, None)
    if journal is None:
        raise PracticeError("no practice account yet: practice.py reset --cash 5000")
    if any(t.get("fingerprint") == fp and t.get("date") == today for t in journal["trades"]):
        raise PracticeError("this order is already in the practice journal today")
    qty = T._f(order.get("qty"))
    stop = T._f(order.get("stop_loss_stop_price")) or T._f(plan.get("stop"))
    target = T._f(order.get("take_profit_limit_price")) or T._f(plan.get("target"))
    if not qty or not stop or not target:
        raise PracticeError("the order needs qty, a stop and a target (a bracket from trader-budget)")
    flat_by = plan.get("flat_by") or cfg.get("flat_by") or T.FLAT_BY
    if local.time() >= hhmm(flat_by):
        raise PracticeError("it is %s, past your flat-by %s: no time left for this trade"
                            % (local.strftime("%H:%M"), flat_by))
    if a.price is not None:
        price = float(a.price)
    else:
        _, price = day_bars(chart_text(sym, local.date(), local.date(), a.offline), sym, local.date(), now,
                            live=a.now is None)
        if price is None:
            raise PracticeError("no price for %s yet today: give --price" % sym)
    price = round(float(price), 2)
    if price <= stop or price >= target:
        raise PracticeError("%s is at %.2f, already %s (stop %.2f, target %.2f): the trade is gone, skip it"
                            % (sym, price, "at or under the stop" if price <= stop else "at or past the target",
                               stop, target))
    loss = round(qty * (price - stop), 2)
    cap = limit(cfg, "max_loss_per_trade")
    if cap and loss > cap + 0.005:
        raise PracticeError("at %.2f the loss at the stop would be %s, over your %s max loss: the price ran; "
                            "size it again (size.py) or skip it" % (price, rs(loss), rs(cap)))
    T.apply_fill(a.portfolio, cfg, sym, "buy", qty, price, today)
    state = T.load_state(a.state)
    state.setdefault("orders", []).append({
        "at": T.ny_iso(now), "date": today, "index": a.index, "fingerprint": fp, "symbol": sym, "side": "buy",
        "qty": order.get("qty"), "kind": "entry", "max_loss": loss, "stop": stop, "plain": T.plain(order),
        "status": "placed", "practice": True, "note": "practice fill at %.2f" % price})
    T.write_json(a.state, state)
    T.log_fill(a.state, now, today, sym, "buy", qty, price)
    journal["trades"].append({
        "id": "%s-%d" % (today, len(journal["trades"]) + 1), "date": today, "symbol": sym, "qty": qty,
        "entry": price, "entry_at": local.strftime("%H:%M"), "plan_entry": T._f(plan.get("entry")),
        "stop": stop, "target": target, "flat_by": flat_by, "risk_per_share": round(price - stop, 2),
        "max_loss": loss, "fingerprint": fp, "status": "open", "auto": bool(a.auto)})
    journal.setdefault("days", {})[today] = "traded"
    T.write_json(a.journal, journal)
    print("Practice buy: %s %s at %.2f (%s), stop %.2f, target %.2f, out by %s. Loss at the stop: %s."
          % (T._str_num(qty), sym, price, local.strftime("%H:%M"), stop, target, flat_by, rs(loss)))
    print("Nothing went to Kite. After %s: practice.py settle (it reads the real bars)." % flat_by)
    return 0


def cmd_settle(a):
    cfg = read_json(a.config, {}) or {}
    journal = read_json(a.journal, None)
    if journal is None:
        raise PracticeError("no practice account yet: practice.py reset --cash 5000")
    now, local = clock(a)
    opened = [t for t in journal["trades"] if t.get("status") == "open"]
    if not opened:
        print("No open practice trades.")
        return 0
    for t in opened:
        day = datetime.date.fromisoformat(t["date"])
        bars, price_now = day_bars(chart_text(t["symbol"], day, local.date(), a.offline), t["symbol"], day, now)
        entry_at = datetime.datetime.combine(day, hhmm(t["entry_at"]))
        day_over = local.date() > day or local.time() >= hhmm(t["flat_by"])
        result = walk(bars, entry_at, t["stop"], t["target"], t["flat_by"], day_over)
        if result is None:
            unreal = (price_now - t["entry"]) * t["qty"] if price_now else None
            print("%s still open: last %s%s; it settles at the stop, the target or %s."
                  % (t["symbol"], "%.2f" % price_now if price_now else "unknown",
                     (" (%s on paper)" % signed(unreal)) if unreal is not None else "", t["flat_by"]))
            continue
        reason, at, price = result
        gross = round((price - t["entry"]) * t["qty"], 2)
        cost = charges(t["entry"] * t["qty"], price * t["qty"])
        net = round(gross - cost, 2)
        risk = t["risk_per_share"] * t["qty"]
        pf = T.apply_fill(a.portfolio, cfg, t["symbol"], "sell", t["qty"], price, t["date"])
        if cost:
            pf["cash"] = round(float(pf.get("cash", 0)) - cost, 2)   # the charges leave the practice cash too
            T.write_json(a.portfolio, pf)
        T.log_fill(a.state, T.eastern_to_utc(datetime.datetime.combine(day, hhmm(at))), t["date"], t["symbol"],
                   "sell", t["qty"], price)
        t.update({"status": "closed", "reason": reason, "exit": price, "exit_at": at, "gross": gross,
                  "charges": cost, "net": net, "r": round(gross / risk, 2) if risk else None})
        word = {"stop": "STOP hit", "target": "TARGET hit", "flat": "out at the flat-by time"}[reason]
        print("%s: %s, %s at %.2f. P&L %s, charges %s, net %s (%+.2fR)."
              % (t["symbol"], word, at, price, signed(gross), rs(cost), signed(net), t["r"] or 0))
    T.write_json(a.journal, journal)
    return 0


def cmd_skip(a):
    journal = read_json(a.journal, None)
    if journal is None:
        raise PracticeError("no practice account yet: practice.py reset --cash 5000")
    now, local = clock(a)
    day = a.date or local.date().isoformat()
    if journal.get("days", {}).get(day) == "traded":
        raise PracticeError("%s already has a practice trade" % day)
    journal.setdefault("days", {})[day] = "skipped: " + a.reason
    T.write_json(a.journal, journal)
    print("Logged %s as a day without a trade: %s." % (day, a.reason))
    return 0


def score(journal):
    closed = [t for t in journal["trades"] if t.get("status") == "closed"]
    nets = [t["net"] for t in closed]
    run, peak, worst = 0.0, 0.0, 0.0
    for n in nets:
        run += n
        peak = max(peak, run)
        worst = min(worst, run - peak)
    days = journal.get("days", {})
    return {
        "closed": len(closed), "wins": sum(1 for n in nets if n > 0), "losses": sum(1 for n in nets if n <= 0),
        "gross": round(sum(t["gross"] for t in closed), 2), "charges": round(sum(t["charges"] for t in closed), 2),
        "net": round(sum(nets), 2),
        "avg_r": round(sum(t["r"] or 0 for t in closed) / len(closed), 2) if closed else None,
        "best": max(closed, key=lambda t: t["net"]) if closed else None,
        "worst": min(closed, key=lambda t: t["net"]) if closed else None,
        "drawdown": round(worst, 2), "open": [t for t in journal["trades"] if t.get("status") == "open"],
        "traded_days": sum(1 for v in days.values() if v == "traded"),
        "skipped_days": sum(1 for v in days.values() if str(v).startswith("skipped")),
        "balance": round(journal["start_cash"] + sum(nets), 2)}


def cmd_score(a):
    journal = read_json(a.journal, None)
    if journal is None:
        raise PracticeError("no practice account yet: practice.py reset --cash 5000")
    s = score(journal)
    if a.json:
        out = dict(s, best=s["best"] and s["best"]["id"], worst=s["worst"] and s["worst"]["id"],
                   open=[t["id"] for t in s["open"]], trades=journal["trades"], days=journal.get("days", {}))
        print(json.dumps(out, indent=2))
        return 0
    print("Practice month from %s with %s of practice money. Nothing goes to any broker."
          % (journal["started"], rs(journal["start_cash"])))
    print("Days: %d traded, %d skipped." % (s["traded_days"], s["skipped_days"]))
    if s["closed"]:
        print("Trades closed: %d. Wins %d, losses %d (win rate %.0f%%)."
              % (s["closed"], s["wins"], s["losses"], 100.0 * s["wins"] / s["closed"]))
        print("P&L %s, charges %s (estimate), net %s. Average %+.2fR a trade."
              % (signed(s["gross"]), rs(s["charges"]), signed(s["net"]), s["avg_r"]))
        print("Best %s (%s, %s), worst %s (%s, %s). Deepest drop from a high: %s."
              % (signed(s["best"]["net"]), s["best"]["symbol"], s["best"]["date"], signed(s["worst"]["net"]),
                 s["worst"]["symbol"], s["worst"]["date"], rs(s["drawdown"])))
        print("")
        print("  date        stock        qty    entry     exit  how         net")
        for t in journal["trades"]:
            if t.get("status") == "closed":
                print("  %s  %-10s %5s %8.2f %8.2f  %-7s %10s" % (t["date"], t["symbol"], T._str_num(t["qty"]),
                                                                 t["entry"], t["exit"], t["reason"], signed(t["net"])))
    else:
        print("No closed trades yet.")
    for t in s["open"]:
        print("Open: %s %s %s from %.2f (settles after %s)." % (t["date"], T._str_num(t["qty"]), t["symbol"],
                                                               t["entry"], t["flat_by"]))
    print("Balance: %s (started with %s)." % (rs(s["balance"]), rs(journal["start_cash"])))
    print("A month of practice is a small sample: read it with the rules in mind, not as a promise.")
    return 0


def main(argv=None):
    T.india_text()
    ap = argparse.ArgumentParser(description="Practice account (trader-broker): paper trades settled from real bars.")
    sub = ap.add_subparsers(dest="cmd")

    def files(p):
        p.add_argument("--journal", default="trader/journal.json")
        p.add_argument("--portfolio", default="trader/portfolio.json")
        p.add_argument("--state", default="trader/state/broker.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--now", help="pretend it is this time (market time), e.g. \"2026-11-20 09:41\"")

    p = sub.add_parser("reset", help="start a practice account")
    files(p)
    p.add_argument("--cash", type=float, required=True)
    p.add_argument("--start", help="first day, YYYY-MM-DD (default today)")
    p.add_argument("--force", action="store_true", help="wipe a journal that already holds trades")
    p = sub.add_parser("open", help="book the practice buy for the ticket you said yes to")
    files(p)
    p.add_argument("--index", type=int, default=1)
    p.add_argument("--price", type=float, help="your fill (default: the live price)")
    p.add_argument("--auto", action="store_true",
                   help="paper autopilot: no yes each time (needs \"paper\": true and \"auto_paper\": true)")
    p.add_argument("--orders", default="trader/orders.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--offline", metavar="PATH", help="a saved chart JSON, or a folder of <SYMBOL>.json")
    p = sub.add_parser("settle", help="close practice trades from the real bars: stop, target or flat")
    files(p)
    p.add_argument("--offline", metavar="PATH")
    p = sub.add_parser("skip", help="log a trading day without a trade")
    files(p)
    p.add_argument("--reason", required=True)
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p = sub.add_parser("score", help="the scoreboard")
    files(p)
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"reset": cmd_reset, "open": cmd_open, "settle": cmd_settle, "skip": cmd_skip,
                "score": cmd_score}[a.cmd](a)
    except (PracticeError, T.TicketError) as e:
        print("practice.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
