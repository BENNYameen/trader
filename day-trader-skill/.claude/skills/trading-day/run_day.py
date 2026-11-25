#!/usr/bin/env python3
"""The paper-trading day, end to end: the stock autopilot (day-trader-skill) and the options paper
trader (options-ensemble) run side by side in two processes, then the day's report. Paper only.

    python run_day.py run       # both, from now to the end of the day (the scheduled task runs this)
    python run_day.py status    # what is open and what happened so far today
    python run_day.py report    # the day's report, saved as trader/reports/YYYY-MM-DD.md
    python run_day.py score     # the month so far, both accounts"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OPT = Path(os.environ.get("OPTIONS_HOME") or REPO.parent / "options-ensemble")
IST = datetime.timedelta(hours=5, minutes=30)
HOLIDAYS = {"2026-11-24", "2026-12-25"}
ENV = dict(os.environ, TRADER_MARKET="in", PYTHONIOENCODING="utf-8")


def now_ist():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0) + IST


def sh(args, cwd):
    p = subprocess.run([sys.executable] + [str(a) for a in args], cwd=str(cwd), env=ENV, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=900)
    return (p.stdout + p.stderr).strip()


def read(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def keep_awake(on=True):
    """Ask Windows not to sleep while the day runs (the screen may still turn off); off again after.
    Lets the laptop use normal sleep settings: it sleeps when no paper day is running."""
    if os.name != "nt":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def alive(pid):
    """Is that process still running? (Windows: asks the kernel; never signals the process.)"""
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259                 # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def cmd_run():
    now = now_ist()
    key = now.date().isoformat()
    if now.weekday() >= 5 or key in HOLIDAYS:
        print("%s: the market is closed today." % now.date())
        return 0
    start = min((read(REPO / "trader" / "journal.json", {}) or {}).get("started", key),
                (read(OPT / "paper" / "ledger.json", {}) or {}).get("start", key))
    if key < start:
        print("%s: the paper month starts on %s." % (key, start))
        return 0
    logs = REPO / "trader" / "state"
    logs.mkdir(parents=True, exist_ok=True)
    lock = logs / "run_day.lock"
    held = read(lock, {}) or {}
    if held.get("date") == key and held.get("pid") and alive(held["pid"]):
        print("%s: today's run is already going (process %s); not starting a second one." % (key, held["pid"]))
        return 0
    lock.write_text(json.dumps({"date": key, "pid": os.getpid(), "started": now.strftime("%H:%M")}),
                    encoding="utf-8")
    print("%s  Paper-trading day started: stocks and options side by side." % now.strftime("%Y-%m-%d %H:%M"),
          flush=True)
    keep_awake(True)
    try:
        with open(logs / "stocks_run.log", "a", encoding="utf-8") as s_log, \
                open(logs / "options_run.log", "a", encoding="utf-8") as o_log:
            procs = [subprocess.Popen([sys.executable, str(HERE / "stocks_auto.py"), "run"], cwd=str(REPO),
                                      env=ENV, stdout=s_log, stderr=subprocess.STDOUT),
                     subprocess.Popen([sys.executable, str(OPT / "paper.py"), "run"], cwd=str(OPT), env=ENV,
                                      stdout=o_log, stderr=subprocess.STDOUT)]
            codes = [p.wait() for p in procs]
    finally:
        keep_awake(False)
        try:
            lock.unlink()
        except OSError:
            pass
    print("%s  Both finished (exit codes %s)." % (now_ist().strftime("%H:%M"), codes), flush=True)
    swing_update()
    return cmd_report()


def swing_update():
    """The stock swing shadow book settles from the day's bars once the day is over."""
    out = sh([HERE / "swing.py", "update"], REPO)
    with open(REPO / "trader" / "state" / "swing_run.log", "a", encoding="utf-8") as fh:
        for line in out.splitlines():
            fh.write("%s  %s\n" % (now_ist().strftime("%Y-%m-%d %H:%M"), line))
    return out


def stock_lines(day):
    journal = read(REPO / "trader" / "journal.json", {}) or {}
    state = (read(REPO / "trader" / "state" / "autopilot.json", {}) or {}).get(day, {})
    out = []
    trades = [t for t in journal.get("trades", []) if t["date"] == day]
    for t in trades:
        line = "- Bought %s %s at Rs %.2f (%s), stop Rs %.2f, target Rs %.2f" % (
            int(t["qty"]) if float(t["qty"]).is_integer() else t["qty"], t["symbol"], t["entry"], t["entry_at"],
            t["stop"], t["target"])
        if t["status"] == "closed":
            line += "; out at Rs %.2f (%s, %s): net Rs %+.2f after Rs %.2f charges" % (
                t["exit"], t["reason"], t["exit_at"], t["net"], t["charges"])
        else:
            line += "; still open"
        out.append(line)
    if not trades:
        out.append("- No trade: %s" % journal.get("days", {}).get(day, state.get("status", "not run yet")))
    if state.get("rejected"):
        out.append("- Looked at and passed over: " + "; ".join("%s (%s)" % kv for kv in state["rejected"].items()))
    return out


def cmd_report(day=None):
    day = day or now_ist().date().isoformat()
    lines = ["# Paper trading day: %s" % day, "",
             "## Stocks (Rs 15,000 practice account, opening-range breakouts)"]
    lines += stock_lines(day)
    lines += ["", "```", sh([REPO / "trader-broker" / "practice.py", "score"], REPO), "```", ""]
    if (REPO / "trader" / "swing" / "journal.json").exists():
        sys.path.insert(0, str(HERE))
        import swing
        lines += ["## Stocks swing shadow (Rs 15,000: same entries, target 2R, hold up to 3 days)"]
        lines += swing.lines_for(REPO, day)
        lines += ["", "```", sh([HERE / "swing.py", "score"], REPO), "```", ""]
    lines += ["## Options (Rs 15,000, NIFTY and SENSEX, Algorithm B; Donchian as a shadow)", "```",
              sh([OPT / "paper.py", "day", "--date", day], OPT), "", sh([OPT / "paper.py", "score"], OPT), "```", "",
              "Paper only: nothing was sent to any broker. Stock fills use real 5-minute bars; option prices "
              "are Black-Scholes estimates from India VIX."]
    text = "\n".join(lines) + "\n"
    out = REPO / "trader" / "reports" / ("%s.md" % day)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print("Saved %s" % out)
    return 0


def cmd_status():
    day = now_ist().date().isoformat()
    print("Stocks:")
    print("\n".join(stock_lines(day)))
    print("Stocks swing shadow (settles from the bars after the day):")
    print(sh([HERE / "swing.py", "score"], REPO))
    print("Options:")
    print(sh([OPT / "paper.py", "day", "--date", day], OPT))
    return 0


def cmd_score():
    print(sh([REPO / "trader-broker" / "practice.py", "score"], REPO))
    print("")
    print(sh([HERE / "swing.py", "score"], REPO))
    print("")
    print(sh([OPT / "paper.py", "score"], OPT))
    us = REPO.parent / "day-trader-us"
    if (us / "autopilot" / "us_auto.py").exists():
        print("")
        print(sh([us / "autopilot" / "us_auto.py", "score"], us))
    return 0


def main(argv=None):
    args = argv or sys.argv[1:] or ["status"]
    cmd = args[0]
    if cmd == "run":
        return cmd_run()
    if cmd == "report":
        return cmd_report(args[1] if len(args) > 1 else None)
    if cmd == "status":
        return cmd_status()
    if cmd == "score":
        return cmd_score()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
