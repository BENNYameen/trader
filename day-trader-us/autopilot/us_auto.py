#!/usr/bin/env python3
"""US paper autopilot: the ORIGINAL day-trader-skill code (git 3d0f4ef, unmodified, in the folders
next to this one) run by the clock on US stocks, with a local practice simulator for the fills.
Paper only: nothing is sent to any broker. Budget Rs 15,000 = $162.66 at 92.22 INR/USD (2026-11-25).

    python autopilot/us_auto.py run        # morning scan, then breakouts until the close, by itself
    python autopilot/us_auto.py tick       # one pass now
    python autopilot/us_auto.py status     # today so far
    python autopilot/us_auto.py report [YYYY-MM-DD]
    python autopilot/us_auto.py score

The original pipeline, step by step (times New York):
  09:00-09:40  scan.py universe (weekly) + scan.py daily -> trader/watchlist.json (pre-market setups)
  09:50-15:30  every 5 minutes: scan.py orb --watchlist (15-minute opening range, 5-minute bars)
  per breakout news.py (24 h) -> exit.py plan (ORIGINAL defaults: stop at the range midpoint,
               target 2R, out by 15:55) -> timemachine.py (60-day replay) -> size.py -> check.py
  the fill     the simulator books it at the live price; exits walk real 5-minute bars, stop first

Autopilot choices (the original leaves picking to a person; these are fixed for the month):
  - a FRESH breakout only (trigger bar closed within 10 minutes), at least 0.15 % over the range
  - skip news tagged earnings, legal, deal, halt or risk, and a Time Machine verdict "strongly
    toward the stop"; of the rest, the best Time Machine lean (at most 5 judged per scan)
  - one position at a time; the original config limits hold: 3 trades a day, the daily loss limit,
    whole shares only (bracket orders), so a stock dearer than the per-order cap cannot be bought"""

import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

US = Path(__file__).resolve().parents[1]
TRADER = US / "trader"
JOURNAL = TRADER / "journal.json"
STATE = TRADER / "state" / "us_autopilot.json"
LOG = TRADER / "state" / "us_autopilot.log"
BROKER = TRADER / "state" / "broker.json"
RED_FLAGS = {"earnings", "legal", "deal", "halt", "risk"}
FRESH_MIN = 10
MAX_JUDGE = 5
UA = "Mozilla/5.0 (compatible; day-trader-us paper test)"
SEC_UA = "day-trader-us paper test research@example.com"
EPOCH = datetime.datetime(1970, 1, 1)
STEP = datetime.timedelta(minutes=5)
PINNED = None


def _risk():
    spec = importlib.util.spec_from_file_location("orig_check", str(US / "trader-risk" / "check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _risk()            # the original calendar: NYSE holidays, early closes, New York time with DST


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def now_et():
    return PINNED or R.to_eastern(utc_now())


def session(d):
    """(open?, entries until, flat by, reason) for New York date d."""
    ok, why = R.trading_day(d)
    if not ok:
        return False, None, None, why
    close = R.EARLY if d.isoformat() in R.NYSE_EARLY_CLOSE else R.CLOSE
    until = min(datetime.time(15, 30), (datetime.datetime.combine(d, close) - datetime.timedelta(minutes=30)).time())
    flat = (datetime.datetime.combine(d, close) - datetime.timedelta(minutes=5)).time()
    return True, until, flat, ""


def log(msg):
    line = "%s ET  %s" % (now_et().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(path))


NOW_FLAG = {"trader-scanner/scan.py", "trader-exit/exit.py", "trader-timemachine/timemachine.py",
            "trader-budget/size.py", "trader-risk/check.py"}


def tool(rel, *args, timeout=900):
    extra = []
    if PINNED is not None:
        if rel in NOW_FLAG:
            extra = ["--now", PINNED.strftime("%Y-%m-%d %H:%M")]
        elif rel == "trader-news/news.py":
            extra = ["--now", R.eastern_to_utc(PINNED).strftime("%Y-%m-%dT%H:%M:00Z")]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.pop("TRADER_MARKET", None)                      # the original code is US-only anyway
    p = subprocess.run([sys.executable, str(US / rel)] + [str(x) for x in args] + extra, cwd=str(US), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def jtool(rel, *args):
    code, out, err = tool(rel, *args)
    try:
        return code, json.loads(out), err
    except ValueError:
        return code, None, (err or out).strip()


# ---------------------------------------------------------------- bars and fills (the simulator)

def rng_for(day):
    """Yahoo range that still holds the 5-minute bars of `day` (counted from the real date)."""
    back = (R.to_eastern(utc_now()).date() - day).days
    return "1d" if back <= 0 else "5d" if back <= 6 else "1mo" if back <= 28 else "60d"


def chart(sym, rng="1d"):
    last = "no answer"
    for host in ("query2", "query1"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=5m" % (
            host, urllib.parse.quote(sym.upper().replace(".", "-")), rng)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))["chart"]["result"][0]
        except Exception as e:                           # retry the other host
            last = str(e)
            time.sleep(1)
    raise RuntimeError("Yahoo did not answer for %s (%s)" % (sym, last))


def bars_of(res, day, as_of_utc):
    """Complete 5-minute bars of New York date `day`: (start ET, o, h, l, c); and the live price."""
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    out = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        vals = [(q.get(k) or [None] * (i + 1))[i] if i < len(q.get(k) or []) else None
                for k in ("open", "high", "low", "close")]
        if ts is None or None in vals or int(ts) % 300:
            continue
        start = EPOCH + datetime.timedelta(seconds=int(ts))
        if start + STEP > as_of_utc:
            continue
        et = R.to_eastern(start)
        if et.date() == day:
            out[et] = (et, float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]))
    bars = [out[k] for k in sorted(out)]
    meta = res.get("meta") or {}
    live = meta.get("regularMarketPrice")
    if PINNED is not None or not live:
        live = bars[-1][4] if bars else None
    return bars, (float(live) if live else None)


def walk(bars, entry_at, stop, target, flat, day_over):
    last = None
    for start, o, h, lo, c in bars:
        end = start + STEP
        if end <= entry_at:
            continue
        if start.time() >= flat:
            break
        running = start < entry_at
        if lo <= stop:
            return "stop", end.strftime("%H:%M"), round(stop if running else min(stop, o), 2)
        if h >= target and not running:
            return "target", end.strftime("%H:%M"), round(target, 2)
        last = (end, c)
    if last and (last[0].time() >= flat or day_over):
        return "flat", last[0].strftime("%H:%M"), round(last[1], 2)
    return None


def us_fees(sell_value, qty):
    """Alpaca: $0 commission. Regulatory fees on the sell: SEC fee and FINRA TAF (estimates)."""
    return round(0.0000278 * sell_value + min(0.000166 * qty, 8.30), 2)


def as_of_utc():
    return R.eastern_to_utc(PINNED) if PINNED else utc_now()


def sim_open(journal, sym, order, plan, now, flat):
    qty = int(float(order["qty"]))
    stop = float(order["stop_loss_stop_price"])
    target = float(order["take_profit_limit_price"])
    bars, price = bars_of(chart(sym, rng_for(now.date())), now.date(), as_of_utc())
    if not price:
        return "no price yet"
    price = round(price, 2)
    if price <= stop or price >= target:
        return "price %.2f is already past the stop or the target" % price
    loss = round(qty * (price - stop), 2)
    cap = float(read(TRADER / "config.json", {}).get("max_loss_per_trade_usd") or 0)
    if cap and loss > cap + 0.005:
        return "at %.2f the loss at the stop would be $%.2f, over the $%.2f limit" % (price, loss, cap)
    key = now.date().isoformat()
    state = read(BROKER, {}) or {}
    state.setdefault("orders", []).append({
        "at": now.strftime("%Y-%m-%dT%H:%M:%S"), "date": key, "symbol": sym, "side": "buy", "qty": str(qty),
        "kind": "entry", "max_loss": loss, "stop": stop, "status": "placed", "practice": True,
        "note": "simulated fill at %.2f (autopilot, paper only)" % price})
    write(BROKER, state)
    journal["trades"].append({
        "id": "%s-%d" % (key, len(journal["trades"]) + 1), "date": key, "symbol": sym, "qty": qty,
        "entry": price, "entry_at": now.strftime("%H:%M"), "stop": stop, "target": target,
        "flat_by": flat.strftime("%H:%M"), "max_loss": loss, "status": "open",
        "plan_entry": plan.get("entry")})
    journal.setdefault("days", {})[key] = "traded"
    write(JOURNAL, journal)
    log("Paper buy: %d %s at $%.2f, stop $%.2f, target $%.2f (2R), out by %s. Loss at the stop: $%.2f."
        % (qty, sym, price, stop, target, flat.strftime("%H:%M"), loss))
    return None


def sim_settle(journal, now):
    changed = False
    for t in [x for x in journal["trades"] if x["status"] == "open"]:
        day = datetime.date.fromisoformat(t["date"])
        bars, price = bars_of(chart(t["symbol"], rng_for(day)), day, as_of_utc())
        flat = datetime.datetime.strptime(t["flat_by"], "%H:%M").time()
        entry_at = datetime.datetime.combine(day, datetime.datetime.strptime(t["entry_at"], "%H:%M").time())
        day_over = now.date() > day or now.time() >= flat
        r = walk(bars, entry_at, t["stop"], t["target"], flat, day_over)
        if not r:
            continue
        reason, at, px = r
        gross = round((px - t["entry"]) * t["qty"], 2)
        cost = us_fees(px * t["qty"], t["qty"])
        risk = (t["entry"] - t["stop"]) * t["qty"]
        t.update({"status": "closed", "reason": reason, "exit": px, "exit_at": at, "gross": gross,
                  "charges": cost, "net": round(gross - cost, 2), "r": round(gross / risk, 2) if risk else None})
        state = read(BROKER, {}) or {}
        state.setdefault("orders", []).append({
            "at": "%sT%s:00" % (t["date"], at), "date": t["date"], "symbol": t["symbol"], "side": "sell",
            "qty": str(t["qty"]), "kind": "exit", "status": "filled", "practice": True,
            "note": "simulated %s at %.2f" % (reason, px)})
        write(BROKER, state)
        word = {"stop": "STOP hit", "target": "TARGET hit", "flat": "out at the flat-by time"}[reason]
        log("%s: %s, %s at $%.2f. P&L $%+.2f, fees $%.2f, net $%+.2f (%+.2fR)."
            % (t["symbol"], word, at, px, gross, cost, t["net"], t["r"] or 0))
        changed = True
    if changed:
        write(JOURNAL, journal)


# ---------------------------------------------------------------- the original pipeline

def morning(st, now):
    if st.get("watchlist"):
        return
    uni = US / "trader" / "universe.txt"
    if not uni.exists() or time.time() - uni.stat().st_mtime > 7 * 86400:
        tool("trader-scanner/scan.py", "universe")
    code, out, err = tool("trader-scanner/scan.py", "daily", "--quiet", timeout=1500)
    wl = read(TRADER / "watchlist.json", {}) or {}
    n = len(wl.get("hits", []))
    st["watchlist"] = "%s: %d setups" % (now.strftime("%H:%M"), n)
    log("morning scan (scan.py daily): %d setups in the watchlist%s" % (n, "" if code == 0 else
                                                                       " (exit %d: %s)" % (code, err[-200:])))


def candidates(now, st, cfg):
    code, doc, err = jtool("trader-scanner/scan.py", "orb", "--watchlist", "trader/watchlist.json", "--json",
                           "--no-write", "--quiet")
    if doc is None:
        if "opening range" not in err and "after" not in err:
            log("scan: %s" % err[-200:])
        return []
    # The original size.py limits, applied early so no time goes on news and replays for a stock it
    # would refuse anyway (whole shares only: one share must fit every cap and the max loss).
    budget = float(cfg.get("budget") or 0) or 1e12
    cap = min(float(cfg.get("max_order_usd") or 1e12),
              budget * float(cfg.get("max_position_pct") or 100) / 100.0,
              budget * (1 - float(cfg.get("cash_buffer_pct") or 0) / 100.0))
    max_loss = float(cfg.get("max_loss_per_trade_usd") or 1e12)
    fresh = []
    for h in doc.get("hits", []):
        sym = h["symbol"]
        close = datetime.datetime.combine(now.date(), datetime.datetime.strptime(h["bar_start"], "%H:%M").time()) + STEP
        if (now - close).total_seconds() / 60 > FRESH_MIN or sym in st["rejected"]:
            continue
        risk = h["price"] - (h["or_high"] + h["or_low"]) / 2.0     # the original stop: the range midpoint
        if h["pct_over"] < 0.15:
            st["rejected"][sym] = "breakout %.2f%%, under 0.15%%" % h["pct_over"]
        elif h["price"] > cap:
            st["rejected"][sym] = "$%.2f: one whole share is over the $%.2f cap" % (h["price"], cap)
        elif risk > max_loss + 0.01:
            st["rejected"][sym] = "one share risks $%.2f to the range midpoint, over the $%.2f max loss" % (
                risk, max_loss)
        else:
            fresh.append(h)
    return sorted(fresh, key=lambda h: -h["pct_over"])[:MAX_JUDGE]


def judge(h, now, st, cfg):
    sym, key = h["symbol"], now.date().isoformat()
    code, news, err = jtool("trader-news/news.py", "--tickers", sym, "--hours", "24", "--json", "--dry-run",
                            "--no-moves", "--user-agent", SEC_UA)
    flags = sorted({tag for it in (news or {}).get("items", []) for tag in it.get("tags", []) if tag in RED_FLAGS})
    if flags:
        st["rejected"][sym] = "news tagged %s" % ", ".join(flags)
        return None
    plan = TRADER / "candidates" / ("%s.json" % sym)
    plan.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = tool("trader-exit/exit.py", "plan", "--symbol", sym, "--entry", h["price"],
                          "--or-high", h["or_high"], "--or-low", h["or_low"], "--setup", "orb", "--time", h["at"],
                          "--date", key, "--interval", "5m", "--write", plan)
    if code != 0:
        st["rejected"][sym] = "plan: %s" % err.strip()[-120:]
        return None
    code, tm, err = jtool("trader-timemachine/timemachine.py", "run", "--plan", plan, "--json")
    if not tm:
        st["rejected"][sym] = "time machine: %s" % err[-120:]
        return None
    verdict, mc = tm.get("verdict", ""), tm.get("mc", {})
    if verdict.startswith("Strongly toward the stop"):
        st["rejected"][sym] = verdict
        return None
    hit = mc.get("p_target", 0) + mc.get("p_stop", 0)
    lean = (mc["p_target"] / hit - 0.5) if hit else -1
    log("candidate %s: breakout +%.2f%% at %s, Time Machine: %s" % (sym, h["pct_over"], h["at"], verdict))
    return lean, plan


def reason_of(text):
    """The line that says why a tool refused: 'No order...' or a BLOCK line, never the disclaimer."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and "not financial advice" not in l]
    for l in lines:
        if l.startswith("No order") or "BLOCK" in l:
            return l[:200]
    return lines[-1][:200] if lines else "failed"


def enter(sym, plan_path, st, journal, now, flat):
    shutil.copy(str(plan_path), str(TRADER / "plan.json"))
    for rel, args, what in (("trader-budget/size.py", ["--write"], "size"), ("trader-risk/check.py", [], "risk")):
        code, out, err = tool(rel, *args)
        if code != 0:
            st["rejected"][sym] = "%s: %s" % (what, reason_of(out + "\n" + err))
            log("%s refused %s: %s" % (what, sym, st["rejected"][sym]))
            return False
    orders = (read(TRADER / "orders.json", {}) or {}).get("orders") or []
    if not orders:
        st["rejected"][sym] = "size: no order"
        return False
    why = sim_open(journal, sym, orders[0], read(plan_path, {}), now, flat)
    if why:
        st["rejected"][sym] = "fill: %s" % why
        log("fill refused %s: %s" % (sym, why))
        return False
    return True


def tick(now):
    """One pass. True when the day is done."""
    key = now.date().isoformat()
    ok, until, flat, why = session(now.date())
    if not ok:
        return True
    journal = read(JOURNAL, None)
    if journal is None or key < journal.get("started", key):
        return True
    cfg = read(TRADER / "config.json", {})
    state = read(STATE, {})
    st = state.setdefault(key, {"status": "watching", "rejected": {}, "scans": []})
    if now.time() < datetime.time(9, 0):
        return False
    if now.time() < datetime.time(9, 50):
        morning(st, now)
        write(STATE, state)
        return False
    if not st.get("watchlist"):
        morning(st, now)                                 # started late: the morning scan still comes first
    sim_settle(journal, now)
    journal = read(JOURNAL, journal)
    mine = [t for t in journal["trades"] if t["date"] == key]
    if any(t["status"] == "open" for t in mine):
        st["status"] = "holding"
        write(STATE, state)
        return False
    cap = int(cfg.get("max_trades_per_day") or 0)
    if mine:
        st["status"] = "traded"
    if (cap and len(mine) >= cap) or st.get("halted") or now.time() > until:
        if not mine and not journal.get("days", {}).get(key):
            reasons = "; ".join("%s: %s" % kv for kv in list(st["rejected"].items())[:6])
            journal.setdefault("days", {})[key] = "skipped: no fresh breakout passed the rules" + (
                " (%s)" % reasons if reasons else "")
            write(JOURNAL, journal)
            log("no trade today: %s" % journal["days"][key])
            st["status"] = "skipped"
        write(STATE, state)
        return True
    for t in mine:
        st["rejected"].setdefault(t["symbol"], "already traded today")
    slot = now.replace(second=0) - datetime.timedelta(minutes=now.minute % 5)
    if slot.strftime("%H:%M") in st["scans"] or (now - slot).total_seconds() < 25:
        return False
    st["scans"].append(slot.strftime("%H:%M"))
    picks = []
    for h in candidates(now, st, cfg):
        j = judge(h, now, st, cfg)
        if j:
            picks.append((j[0], h["symbol"], j[1]))
    write(STATE, state)
    for lean, sym, plan in sorted(picks, reverse=True):
        if enter(sym, plan, st, journal, now, flat):
            st["status"] = "traded"
            break
        if "daily loss" in st["rejected"].get(sym, ""):
            st["halted"] = "the daily loss limit is used up"
            log("daily loss limit reached; no more entries today")
            break
    write(STATE, state)
    return False


# ---------------------------------------------------------------- reports

def score_text():
    j = read(JOURNAL, None)
    if j is None:
        return "No US paper journal yet."
    closed = [t for t in j["trades"] if t["status"] == "closed"]
    opened = [t for t in j["trades"] if t["status"] == "open"]
    net = sum(t["net"] for t in closed)
    wins = [t for t in closed if t["net"] > 0]
    days = j.get("days", {})
    lines = ["US paper month (original day-trader-skill code) from %s: $%.2f (Rs 15,000 at %.2f INR/USD). "
             "Paper only." % (j["started"], j["start_cash"], j["usd_inr"]),
             "Days: %d traded, %d skipped." % (sum(1 for v in days.values() if v == "traded"),
                                              sum(1 for v in days.values() if str(v).startswith("skipped")))]
    if closed:
        lines.append("Trades closed: %d. Wins %d, losses %d (win rate %d%%). Net $%+.2f after $%.2f fees "
                     "(Rs %+.0f)." % (len(closed), len(wins), len(closed) - len(wins),
                                      round(100.0 * len(wins) / len(closed)), net,
                                      sum(t["charges"] for t in closed), net * j["usd_inr"]))
        lines.append("")
        lines.append("  date        stock   qty     entry      exit  how       net")
        for t in closed:
            lines.append("  %s  %-6s %4d  %8.2f  %8.2f  %-7s %+7.2f" % (t["date"], t["symbol"], t["qty"], t["entry"],
                                                                     t["exit"], t["reason"], t["net"]))
    else:
        lines.append("No closed trades yet.")
    for t in opened:
        lines.append("Open: %d %s at $%.2f (stop $%.2f, target $%.2f)" % (t["qty"], t["symbol"], t["entry"],
                                                                         t["stop"], t["target"]))
    lines.append("Balance: $%.2f (started with $%.2f)." % (j["start_cash"] + net, j["start_cash"]))
    return "\n".join(lines)


def day_lines(day):
    j = read(JOURNAL, {}) or {}
    st = (read(STATE, {}) or {}).get(day, {})
    out = []
    for t in [x for x in j.get("trades", []) if x["date"] == day]:
        line = "- Bought %d %s at $%.2f (%s ET), stop $%.2f, target $%.2f" % (
            t["qty"], t["symbol"], t["entry"], t["entry_at"], t["stop"], t["target"])
        line += ("; out at $%.2f (%s, %s): net $%+.2f" % (t["exit"], t["reason"], t["exit_at"], t["net"])
                 if t["status"] == "closed" else "; still open")
        out.append(line)
    if not out:
        out.append("- No trade: %s" % j.get("days", {}).get(day, st.get("status", "not run yet")))
    if st.get("watchlist"):
        out.append("- Morning scan: %s" % st["watchlist"])
    if st.get("rejected"):
        items = list(st["rejected"].items())
        out.append("- Passed over (%d): %s%s" % (len(items), "; ".join("%s (%s)" % kv for kv in items[:12]),
                                                 " ..." if len(items) > 12 else ""))
    return out


def cmd_report(day=None):
    day = day or now_et().date().isoformat()
    text = "\n".join(["# US paper day (original repo code): %s" % day, ""] + day_lines(day) +
                     ["", "```", score_text(), "```", "",
                      "Paper only: nothing went to any broker. Fills are simulated from real 5-minute Yahoo bars."]) + "\n"
    out = TRADER / "reports" / ("%s.md" % day)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print("Saved %s" % out)
    return 0


def main(argv=None):
    args = list(argv or sys.argv[1:]) or ["status"]
    cmd = args[0]
    if cmd == "run":
        lock = TRADER / "state" / "us_run.lock"
        now = now_et()
        is_open, _, _, why = session(now.date())
        if not is_open:                                   # a daily schedule: weekends and holidays end here
            print("%s: the US market is closed today (%s)." % (now.date(), why or "weekend"))
            return 0
        old = read(lock, {}) or {}
        if old.get("date") == now.date().isoformat() and old.get("pid") and _alive(old["pid"]):
            print("today's US run is already going (process %s)" % old["pid"])
            return 0
        write(lock, {"date": now.date().isoformat(), "pid": os.getpid()})
        log("US autopilot started.")
        keep_awake(True)
        try:
            while True:
                now = now_et()
                try:
                    done = tick(now)
                except Exception as e:
                    log("tick failed (%s): trying again in a minute" % e)
                    done = False
                if done or now.time() >= datetime.time(16, 10):
                    log("US autopilot finished for %s." % now.date())
                    break
                time.sleep(max(5, 60 - now_et().second + 3))
        finally:
            keep_awake(False)
            try:
                lock.unlink()
            except OSError:
                pass
        return cmd_report(now.date().isoformat())
    if cmd == "tick":
        return 0 if tick(now_et()) else 2
    if cmd == "status":
        print("\n".join(day_lines(now_et().date().isoformat())))
        return 0
    if cmd == "report":
        return cmd_report(args[1] if len(args) > 1 else None)
    if cmd == "score":
        print(score_text())
        return 0
    if cmd == "replay":                                  # a code test on a past day, in a throwaway copy
        global PINNED
        day = datetime.date.fromisoformat(args[1])
        t = datetime.datetime.combine(day, datetime.time(9, 50, 30))
        while t.time() <= datetime.time(16, 0):
            PINNED = t
            if tick(t):
                break
            t += STEP
        PINNED = None
        print(score_text())
        return 0
    print(__doc__)
    return 1


def keep_awake(on=True):
    """Ask Windows not to sleep while the run is working (the screen may still turn off)."""
    if os.name != "nt":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def _alive(pid):
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
