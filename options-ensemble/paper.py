#!/usr/bin/env python3
"""Paper trading for options-ensemble: Algorithm B trades a paper account on NIFTY and SENSEX
options, Donchian breakout keeps a shadow book. Standard library only. Nothing goes to a broker.

    python paper.py reset --cash 15000 --start 2026-11-20   # start the month (refuses to wipe trades)
    python paper.py run                                     # live, 9:15 to the end of the day, by itself
    python paper.py tick                                    # one pass now (entries due, exits)
    python paper.py replay --date 2026-11-19                # a past day, as if live, into its own file
    python paper.py score                                   # both books
    python paper.py day --date 2026-11-20                   # one day's trades, for the daily report"""

import argparse
import datetime
import json
import os
import sys
import time

from oe import live as L

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "paper", "ledger.json")
LOG = os.path.join(HERE, "paper", "log.txt")


def logger(path):
    def log(msg):
        line = "%s  %s" % (L.now_ist().strftime("%Y-%m-%d %H:%M:%S"), msg)
        print(line, flush=True)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return log


def rs(x):
    return ("-" if x < 0 else "") + "Rs " + "{:,.2f}".format(abs(x))


def cmd_reset(a):
    if os.path.exists(a.ledger):
        old = L.load(a.ledger)
        if any(b["trades"] for b in old["books"].values()) and not a.force:
            print("paper.py: %s already holds trades; keep them or start over with --force" % a.ledger, file=sys.stderr)
            return 1
    L.save(a.ledger, L.new_ledger(a.cash, a.start))
    print("Options paper account ready: %s from %s, books: %s." % (
        rs(a.cash), a.start, ", ".join(n for _, n in L.BOOKS)))
    for i, r in enumerate(L.RULES, 1):
        print("  %d. %s" % (i, r))
    return 0


def _ledger(a):
    if not os.path.exists(a.ledger):
        print("paper.py: no ledger yet: paper.py reset --cash 15000", file=sys.stderr)
        return None
    return L.load(a.ledger)


def cmd_tick(a):
    ledger = _ledger(a)
    if ledger is None:
        return 1
    now = datetime.datetime.strptime(a.now, "%Y-%m-%d %H:%M") if a.now else L.now_ist()
    done = L.tick(ledger, L.LiveData(), now, {}, live=True, log=logger(a.log))
    L.save(a.ledger, ledger)
    return 0 if done else 2


def cmd_run(a):
    ledger = _ledger(a)
    if ledger is None:
        return 1
    log, data, brains = logger(a.log), L.LiveData(), {}
    log("Options paper run started.")
    while True:
        now = L.now_ist()
        try:
            done = L.tick(ledger, data, now, brains, live=True, log=log)
            L.save(a.ledger, ledger)
        except Exception as e:                 # a network hiccup must not end the day
            log("tick failed (%s): trying again in a minute" % e)
            done = now.time() >= datetime.time(15, 50)
        if done:
            log("Options paper run finished for %s." % now.date())
            return 0
        time.sleep(max(5, 60 - L.now_ist().second + 3))   # just after each minute turns


def cmd_replay(a):
    day = datetime.date.fromisoformat(a.date)
    path = a.out or os.path.join(HERE, "paper", "replay-%s.json" % day)
    ledger = L.new_ledger(a.cash, day.isoformat())
    data, brains, log = L.ReplayData(day), {}, (lambda m: print("  " + m))
    print("Replay of %s (only bars complete at each moment are used):" % day)
    t = datetime.datetime.combine(day, datetime.time(9, 20))
    while t.time() <= datetime.time(15, 50):
        if L.tick(ledger, data, t, brains, live=False, log=log):
            break
        t += datetime.timedelta(minutes=5)
    L.save(path, ledger)
    for b, n in L.BOOKS:
        st = ledger["days"].get(day.isoformat(), {}).get(b, {})
        print("  %s: %s (checked %s)" % (n, st.get("status"), ", ".join(st.get("checked", [])) or "none"))
    print("Saved %s. Brains: %s" % (path, "; ".join("%s top 5 = %s" % (ix, ", ".join(br.top_names))
                                                   for ix, br in brains.items())))
    return 0


def cmd_score(a):
    ledger = _ledger(a)
    if ledger is None:
        return 1
    s = L.score(ledger)
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    print("Options paper account from %s, %s each book. Paper only: estimated prices." % (
        ledger["start"], rs(ledger["start_cash"])))
    for book, _ in L.BOOKS:
        m = s[book]
        rate = (" (win rate %.0f%%)" % (100.0 * m["wins"] / m["trades"])) if m["trades"] else ""
        print("%s: %d trades, %d wins, %d losses%s. Net %s after %s charges. Balance %s. Deepest drop %s. "
              "Days: %d traded, %d no signal, %d missed." % (
                  m["name"], m["trades"], m["wins"], m["losses"], rate, rs(m["net"]), rs(m["charges"]),
                  rs(m["balance"]), rs(m["max_drawdown"]), m["days"]["traded"], m["days"]["no signal"],
                  m["days"]["missed"]))
    return 0


def cmd_day(a):
    ledger = _ledger(a)
    if ledger is None:
        return 1
    key = a.date or L.now_ist().date().isoformat()
    for book, name in L.BOOKS:
        st = ledger["days"].get(key, {}).get(book, {})
        trades = [t for t in ledger["books"][book]["trades"] if t["date"] == key]
        if not trades:
            print("%s: no trade (%s)." % (name, st.get("status", "not run")))
        for t in trades:
            line = "%s: %s %d %s, lot %d, in at %s Rs %.2f (spot %.2f)" % (
                name, t["index"], t["strike"], t["side"], t["lot"], t["decision"], t["entry"], t["spot"])
            if t["status"] == "closed":
                line += ", out at %s Rs %.2f (%s): net %s" % (t["exit_time"], t["exit"], t["reason"], rs(t["net"]))
            else:
                line += ", still open"
            print(line)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    for name in ("reset", "run", "tick", "replay", "score", "day"):
        p = sub.add_parser(name)
        p.add_argument("--ledger", default=LEDGER)
        p.add_argument("--log", default=LOG)
        if name == "reset":
            p.add_argument("--cash", type=float, required=True)
            p.add_argument("--start", default=L.now_ist().date().isoformat())
            p.add_argument("--force", action="store_true")
        if name == "tick":
            p.add_argument("--now", help="\"YYYY-MM-DD HH:MM\" India time")
        if name == "replay":
            p.add_argument("--date", required=True)
            p.add_argument("--cash", type=float, default=15000.0)
            p.add_argument("--out")
        if name == "score":
            p.add_argument("--json", action="store_true")
        if name == "day":
            p.add_argument("--date")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    return {"reset": cmd_reset, "run": cmd_run, "tick": cmd_tick, "replay": cmd_replay, "score": cmd_score,
            "day": cmd_day}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
