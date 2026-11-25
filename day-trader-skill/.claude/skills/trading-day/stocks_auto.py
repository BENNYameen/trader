#!/usr/bin/env python3
"""Stock autopilot for the paper month (day-trader-skill, India mode). It does by the clock what
the rules say a person does: scan, check, plan, replay, size, check the risk, then the practice
entry and the exit. Paper only: it ends in practice.py, never at a broker.

    python stocks_auto.py run      # 9:35 to the end of the day, by itself
    python stocks_auto.py tick     # one pass now
    python stocks_auto.py replay 2026-11-19 --home C:/temp/test   # a day of today's data, in a test folder

Rules (fixed for the month, the same as the practice journal's):
  - 15-minute opening-range breakout on 5-minute bars, 48 liquid NSE stocks, 9:35 to 14:30
  - only a FRESH breakout: the trigger bar closed in the last 10 minutes (never chase)
  - skip: breakout under 0.15 %; not 2 shares under the per-stock cap; news in the last 24 hours
    tagged earnings, legal, deal, halt or risk; a Time Machine verdict of "strongly toward the stop"
  - of the rest, the best Time Machine lean; then trader-budget sizes it and trader-risk must PASS
  - one trade a day; stop at the opening-range midpoint, target 1R, out by 15:05"""

import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOME = Path(os.environ.get("TRADER_HOME") or REPO)     # the folder that holds trader/ (a test can point elsewhere)
TRADER = HOME / "trader"
STATE = TRADER / "state" / "autopilot.json"
LOG = TRADER / "state" / "autopilot.log"
PINNED = None                                          # replay: the simulated time handed to every tool
IST = datetime.timedelta(hours=5, minutes=30)
SYMBOLS = ("RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,SBIN,AXISBANK,KOTAKBANK,ITC,LT,HINDUNILVR,BHARTIARTL,"
           "BAJFINANCE,MARUTI,M&M,SUNPHARMA,TITAN,ULTRACEMCO,NTPC,POWERGRID,ONGC,COALINDIA,TATASTEEL,JSWSTEEL,"
           "HINDALCO,ADANIENT,ADANIPORTS,WIPRO,HCLTECH,TECHM,ASIANPAINT,NESTLEIND,BAJAJ-AUTO,HEROMOTOCO,"
           "EICHERMOT,DRREDDY,CIPLA,BEL,TRENT,IRFC,SUZLON,ETERNAL,JIOFIN,BPCL,GRASIM,INDUSINDBK,SHRIRAMFIN,"
           "APOLLOHOSP")
RED_FLAGS = {"earnings", "legal", "deal", "halt", "risk"}
FROM, UNTIL = datetime.time(9, 35), datetime.time(14, 30)
FRESH_MIN = 10
HOLIDAYS = {"2026-11-24", "2026-12-25"}       # NSE weekday holidays left in the month


def now_ist():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0) + IST


def log(msg):
    line = "%s  %s" % (now_ist().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


NOW_FLAG = {"trader-scanner/scan.py", "trader-exit/exit.py", "trader-timemachine/timemachine.py",
            "trader-budget/size.py", "trader-risk/check.py", "trader-broker/practice.py"}


def tool(rel, *args):
    env = dict(os.environ, TRADER_MARKET="in", PYTHONIOENCODING="utf-8")
    extra = []
    if PINNED is not None:
        if rel in NOW_FLAG:
            extra = ["--now", PINNED.strftime("%Y-%m-%d %H:%M")]
        elif rel == "trader-news/news.py":
            extra = ["--now", (PINNED - IST).strftime("%Y-%m-%dT%H:%M:00Z")]
    p = subprocess.run([sys.executable, str(REPO / rel)] + [str(x) for x in args] + extra, cwd=str(HOME),
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return p.returncode, p.stdout, p.stderr


def jtool(rel, *args):
    code, out, err = tool(rel, *args)
    try:
        return code, json.loads(out), err
    except ValueError:
        return code, None, (err or out).strip()


def read(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)


def money(cfg, name):
    v = cfg.get(name + "_inr", cfg.get(name + "_usd"))
    return float(v) if v is not None else None


def candidates(now, st, cfg):
    """Fresh breakouts that pass the quick rules."""
    code, doc, err = jtool("trader-scanner/scan.py", "orb", "--symbols", SYMBOLS, "--json", "--no-write",
                           "--quiet")
    if doc is None:
        if "opening range runs" not in err and "after" not in err:
            log("scan: %s" % err[:200])
        return []
    cap = money(cfg, "max_order") or 1e12
    out = []
    for h in doc.get("hits", []):
        sym = h["symbol"]
        close = datetime.datetime.combine(now.date(), datetime.datetime.strptime(h["bar_start"], "%H:%M").time()) \
            + datetime.timedelta(minutes=5)
        if (now - close).total_seconds() / 60 > FRESH_MIN or sym in st["rejected"]:
            continue
        if h["pct_over"] < 0.15:
            st["rejected"][sym] = "breakout %.2f%%, under 0.15%%" % h["pct_over"]
        elif h["price"] * 2 > cap:
            st["rejected"][sym] = "Rs %.2f: not 2 shares under the Rs %.0f cap" % (h["price"], cap)
        else:
            out.append(h)
    return out


def judge(h, now, st, cfg):
    """News, plan and Time Machine for one candidate -> (lean, plan path) or None (rejected)."""
    sym, key = h["symbol"], now.date().isoformat()
    code, news, err = jtool("trader-news/news.py", "--tickers", sym, "--hours", "24", "--json", "--dry-run",
                            "--no-moves")
    flags = sorted({tag for it in (news or {}).get("items", []) for tag in it.get("tags", []) if tag in RED_FLAGS})
    if flags:
        st["rejected"][sym] = "news tagged %s" % ", ".join(flags)
        return None
    plan = TRADER / "candidates" / ("%s.json" % sym)
    plan.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = tool("trader-exit/exit.py", "plan", "--symbol", sym, "--entry", h["price"],
                          "--or-high", h["or_high"], "--or-low", h["or_low"], "--setup", "orb", "--time", h["at"],
                          "--date", key, "--interval", "5m", "--stop", "or-mid", "--target", "1R", "--write", plan)
    if code != 0:
        st["rejected"][sym] = "plan: %s" % err.strip()[:120]
        return None
    code, tm, err = jtool("trader-timemachine/timemachine.py", "run", "--plan", plan,
                          "--until", cfg.get("flat_by", "15:05"), "--json")
    if not tm:
        st["rejected"][sym] = "time machine: %s" % err[:120]
        return None
    verdict, mc = tm.get("verdict", ""), tm.get("mc", {})
    if verdict.startswith("Strongly toward the stop"):
        st["rejected"][sym] = verdict
        return None
    hit = mc.get("p_target", 0) + mc.get("p_stop", 0)
    lean = (mc["p_target"] / hit - 0.5) if hit else -1
    log("candidate %s: breakout +%.2f%% at %s, Time Machine: %s" % (sym, h["pct_over"], h["at"], verdict))
    return lean, plan


def enter(sym, plan, st):
    shutil.copy(str(plan), str(TRADER / "plan.json"))
    for rel, args, what in (("trader-budget/size.py", ["--write"], "size"), ("trader-risk/check.py", [], "risk"),
                            ("trader-broker/practice.py", ["open", "--auto"], "practice entry")):
        code, out, err = tool(rel, *args)
        if code != 0:
            st["rejected"][sym] = "%s: %s" % (what, (err or out).strip().splitlines()[-1][:160] if (err or out).strip()
                                               else "failed")
            log("%s refused %s: %s" % (what, sym, st["rejected"][sym]))
            return False
        if what == "practice entry":
            log(out.strip())
    return True


def tick(now):
    """One pass. Returns True when the stock side is done for the day."""
    key = now.date().isoformat()
    if now.weekday() >= 5 or key in HOLIDAYS:
        return True
    if now.time() < FROM:
        return False
    cfg = read(TRADER / "config.json", {})
    journal = read(TRADER / "journal.json", None)
    if journal is None:
        log("no practice journal: practice.py reset first")
        return True
    if key < journal.get("started", key):
        return True                                   # the month has not started: nothing to log
    state = read(STATE, {})
    st = state.setdefault(key, {"status": "watching", "rejected": {}, "scans": []})
    mine = [t for t in journal["trades"] if t["date"] == key]
    if mine:
        if any(t["status"] == "open" for t in mine):
            code, out, err = tool("trader-broker/practice.py", "settle")
            if "still open" not in out and out.strip():
                log(out.strip())
        mine = [t for t in read(TRADER / "journal.json", journal)["trades"] if t["date"] == key]
        st["status"] = "traded"
        write(STATE, state)
        if any(t["status"] == "open" for t in mine):
            return False                              # one position at a time: manage it first
        cap = int(cfg.get("max_trades_per_day") or 0)  # 0 = no count limit (the daily loss limit still holds)
        if (cap and len(mine) >= cap) or now.time() > UNTIL or st.get("halted"):
            return True
        for t in mine:                                # a stock traded today is not bought again today
            st["rejected"].setdefault(t["symbol"], "already traded today")
    elif journal.get("days", {}).get(key, "").startswith("skipped"):
        return True
    if now.time() > UNTIL:
        reasons = "; ".join("%s: %s" % kv for kv in list(st["rejected"].items())[:6])
        why = "no fresh breakout passed the rules" + (" (%s)" % reasons if reasons else "")
        tool("trader-broker/practice.py", "skip", "--reason", why[:300])
        st["status"] = "skipped"
        write(STATE, state)
        log("stocks: no trade today: %s" % why)
        return True
    slot = now.replace(second=0) - datetime.timedelta(minutes=now.minute % 5)
    if slot.strftime("%H:%M") in st["scans"] or (now - slot).total_seconds() < 25:
        return False                                  # once per 5-minute bar, just after it closes
    st["scans"].append(slot.strftime("%H:%M"))
    picks = []
    for h in candidates(now, st, cfg):
        judged = judge(h, now, st, cfg)
        if judged:
            picks.append((judged[0], h["symbol"], judged[1]))
    write(STATE, state)
    for lean, sym, plan in sorted(picks, reverse=True):
        if enter(sym, plan, st):
            st["status"] = "traded"
            break
        if "daily loss" in st["rejected"].get(sym, ""):
            st["halted"] = "the daily loss limit is used up"   # no more entries today
            log("stocks: daily loss limit reached; no more entries today")
            break
    write(STATE, state)
    return False


def replay(day, home):
    """A past session (Yahoo keeps the day's 1-minute and 5-minute bars), every 5 minutes, in a
    separate folder: a test of the whole path, never the real journal."""
    global PINNED, HOME, TRADER, STATE, LOG
    HOME = Path(home)
    TRADER, STATE, LOG = HOME / "trader", HOME / "trader" / "state" / "autopilot.json", \
        HOME / "trader" / "state" / "autopilot.log"
    if HOME.resolve() == REPO.resolve():
        raise SystemExit("replay needs --home: a test folder, not the real one")
    TRADER.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(REPO / "trader" / "config.json"), str(TRADER / "config.json"))
    for name in ("journal.json", "portfolio.json", "plan.json", "orders.json"):
        if (TRADER / name).exists():
            (TRADER / name).unlink()
    for p in (TRADER / "state").glob("*"):
        p.unlink()
    PINNED = datetime.datetime.combine(day, datetime.time(9, 20))
    tool("trader-broker/practice.py", "reset", "--cash", read(TRADER / "config.json", {}).get("budget", 15000))
    t = datetime.datetime.combine(day, datetime.time(9, 35, 30))
    while t.time() <= datetime.time(15, 30):
        PINNED = t
        if tick(t):
            break
        t += datetime.timedelta(minutes=5)
    PINNED = None
    code, out, err = tool("trader-broker/practice.py", "score")
    print(out)
    return 0


def main(argv=None):
    args = argv or sys.argv[1:] or ["tick"]
    cmd = args[0]
    if cmd == "replay":
        home = args[args.index("--home") + 1] if "--home" in args else None
        if not home:
            raise SystemExit("replay DATE --home TEST_FOLDER")
        return replay(datetime.date.fromisoformat(args[1]), home)
    if cmd == "tick":
        return 0 if tick(now_ist()) else 2
    if cmd == "run":
        log("Stock autopilot started.")
        while True:
            now = now_ist()
            try:
                done = tick(now)
            except Exception as e:                   # a network hiccup must not end the day
                log("stock tick failed (%s): trying again in a minute" % e)
                done = now.time() >= datetime.time(15, 40)
            if done or now.time() >= datetime.time(15, 40):
                log("Stock autopilot finished for %s." % now.date())
                return 0
            time.sleep(max(5, 60 - now_ist().second + 3))
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
