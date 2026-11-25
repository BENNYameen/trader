#!/usr/bin/env python3
"""Move the paper-trading month to another machine (a server that runs every day), safely.

    python move_to_server.py pack [--out DIR]   # on the OLD machine: one zip of the three folders
    python move_to_server.py check              # on the NEW machine: is everything ready?

pack zips trading/day-trader-skill, trading/options-ensemble and trading/day-trader-us, including the
journals, ledgers and configs that git does not keep (they live in gitignored folders). It refuses while
a run is going, so the copy is never taken halfway through a day. Unzip it on the server into a folder
OUTSIDE OneDrive (for example C:\\trading), so the two machines never share the same live files.

Only one machine may run the schedule: after the server passes `check` and its tasks are registered,
disable the old machine's task (schtasks /Change /TN PaperTradingDay /Disable)."""

import datetime
import json
import os
import platform
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TRADING = REPO.parent
FOLDERS = ("day-trader-skill", "options-ensemble", "day-trader-us")
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_FILES = {"run_day.lock", "us_run.lock"}
UA = "Mozilla/5.0 (compatible; paper-trading self-test)"


def read(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def alive(pid):
    sys.path.insert(0, str(HERE))
    from run_day import alive as _alive
    return _alive(pid)


def running():
    """Runs that are going right now (a lock whose process is alive)."""
    out = []
    for lock in (REPO / "trader" / "state" / "run_day.lock", TRADING / "day-trader-us" / "trader" / "state" / "us_run.lock"):
        held = read(lock, {}) or {}
        if held.get("pid") and alive(held["pid"]):
            out.append("%s (process %s, %s)" % (lock.parent.parent.parent.name, held["pid"], held.get("date", "")))
    return out


def cmd_pack(out_dir):
    busy = running()
    if busy:
        print("Not packing: a run is going right now: %s." % "; ".join(busy))
        print("Pack when nothing runs (India runs 09:10-15:20 IST, the US 19:30-02:40 IST), or stop the run first.")
        return 1
    missing = [f for f in FOLDERS if not (TRADING / f).is_dir()]
    if missing:
        print("Missing folder(s) next to day-trader-skill: %s" % ", ".join(missing))
        return 1
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = Path(out_dir or TRADING.parent) / ("trading-move-%s.zip" % stamp)
    n = 0
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as z:
        for f in FOLDERS:
            for root, dirs, files in os.walk(str(TRADING / f)):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in files:
                    if name in SKIP_FILES or name.endswith((".pyc", ".tmp")):
                        continue
                    full = Path(root) / name
                    z.write(str(full), str(Path("trading") / full.relative_to(TRADING)))
                    n += 1
        # Claude Code's notes for this project (memory) and the chat history, so a Claude session on the
        # new machine can pick up the context: trading/claude-context/{memory,chat}/
        proj = Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(REPO))
        for sub, pattern in (("memory", "memory/*.md"), ("chat", "*.jsonl")):
            for p in sorted(proj.glob(pattern)) if proj.is_dir() else []:
                z.write(str(p), str(Path("trading") / "claude-context" / sub / p.name))
                n += 1
    print("Packed %d files into %s (%.1f MB)." % (n, out, out.stat().st_size / 1e6))
    print("Next, on the server: unzip it into a folder outside OneDrive (it makes a 'trading' folder),")
    print("install Python 3 from python.org, then run setup_server.ps1 and 'move_to_server.py check'.")
    return 0


def fetch(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m" % symbol
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))["chart"]["result"][0]
        return True, "%s bars" % len(res.get("timestamp") or [])
    except Exception as e:
        return False, str(e)[:80]


def cmd_check():
    ok_all = True

    def line(ok, text):
        nonlocal ok_all
        ok_all = ok_all and ok is not False
        print("%-5s %s" % ({True: "OK", False: "FAIL", None: "NOTE"}[ok], text))

    line(sys.version_info >= (3, 8), "Python %s at %s" % (platform.python_version(), sys.executable))
    for f in FOLDERS:
        line((TRADING / f).is_dir(), "folder %s" % (TRADING / f))
    j = read(REPO / "trader" / "journal.json")
    line(j is not None, "India stocks journal: %s" % (
        "Rs %.2f start, %d trades" % (j.get("start_cash", 0), len(j.get("trades", []))) if j else "missing"))
    line((REPO / "trader" / "config.json").exists(), "India stocks config (market in, paper)")
    sw = read(REPO / "trader" / "swing" / "journal.json")
    line(sw is not None, "India swing shadow book: %s" % ("cash Rs %.2f" % sw["cash"] if sw else "missing"))
    led = read(TRADING / "options-ensemble" / "paper" / "ledger.json")
    line(led is not None, "Options ledger: %s" % (", ".join("%s Rs %.2f" % (k, v["cash"]) for k, v in led["books"].items())
                                                 if led else "missing"))
    us = read(TRADING / "day-trader-us" / "trader" / "journal.json")
    line(us is not None, "US journal: %s" % ("$%.2f start, %d trades" % (us["start_cash"], len(us["trades"])) if us else "missing"))
    utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)
    local = datetime.datetime.now().replace(microsecond=0)
    line(None, "clock: this machine %s (UTC%+.1f h); India %s; UTC %s" % (
        local.strftime("%H:%M"), (local - utc).total_seconds() / 3600.0,
        (utc + datetime.timedelta(hours=5, minutes=30)).strftime("%H:%M"), utc.strftime("%H:%M")))
    for sym in ("RELIANCE.NS", "%5ENSEI", "%5EINDIAVIX", "AAPL"):
        ok, why = fetch(sym)
        line(ok, "Yahoo %s: %s" % (sym.replace("%5E", "^"), why))
    busy = running()
    line(None, "runs going now: %s" % ("; ".join(busy) if busy else "none"))
    if os.name == "nt":
        for name in ("PaperTradingDay", "PaperTradingUS"):
            p = subprocess.run(["schtasks", "/Query", "/TN", name, "/FO", "LIST"], capture_output=True, text=True)
            nxt = [l.split(":", 1)[1].strip() for l in p.stdout.splitlines() if l.startswith("Next Run Time")]
            line(p.returncode == 0, "scheduled task %s: %s" % (name, ("next run %s" % nxt[0]) if nxt else
                                                                 "not registered (run setup_server.ps1)"))
    print("")
    print("All set." if ok_all else "Fix the FAIL lines above, then run this again.")
    return 0 if ok_all else 1


def main(argv=None):
    args = list(argv or sys.argv[1:])
    if args and args[0] == "pack":
        return cmd_pack(args[args.index("--out") + 1] if "--out" in args else None)
    if args and args[0] == "check":
        return cmd_check()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
