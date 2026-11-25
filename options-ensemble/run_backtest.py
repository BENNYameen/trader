#!/usr/bin/env python3
"""Backtest every indicator, three ways of combining them, and random direction, on NIFTY
options bought on paper (same day, one lot, at most one trade a day). Standard library only.

    python run_backtest.py                      # hourly bars, about 3 years: ~1 year to learn, ~2 to test
    python run_backtest.py --interval 5m        # 5-minute bars, the last 60 days (a short test)
    python run_backtest.py --workers 4 --seeds 300 --capital 15000 --max-loss 1500

The strategies run side by side in separate processes (--workers). A result is only worth
something when it beats most of the random-direction runs AND stays positive after costs."""

import argparse
import concurrent.futures as cf
import datetime
import json
import os
import statistics
import sys
import time

from oe import backtest as B
from oe import data as D
from oe import methods as M
from oe import options as O

HERE = os.path.dirname(os.path.abspath(__file__))


def pct_beaten(x, xs):
    return 100.0 * sum(1 for v in xs if v < x) / len(xs) if xs else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--interval", default="60m", choices=["60m", "15m", "5m"])
    ap.add_argument("--index", default="NIFTY", choices=sorted(O.INDICES))
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 2))
    ap.add_argument("--seeds", type=int, default=200, help="random-direction runs for the yardstick")
    ap.add_argument("--capital", type=float)
    ap.add_argument("--max-loss", type=float)
    ap.add_argument("--stop", type=float, help="premium stop, e.g. 0.20")
    ap.add_argument("--target", type=float, help="premium target, e.g. 0.40")
    ap.add_argument("--offline-bars")
    ap.add_argument("--offline-vix")
    a = ap.parse_args(argv)
    cfg = dict(B.DEFAULTS, index=a.index)
    for k, v in (("capital", a.capital), ("max_loss", a.max_loss), ("stop_pct", a.stop), ("target_pct", a.target)):
        if v is not None:
            cfg[k] = v
    if a.interval == "5m":
        cfg.update(warmup_days=30, block_days=10)
    elif a.interval == "15m":
        cfg.update(warmup_days=30, block_days=10)

    t0 = time.time()
    bars, vix = D.load(a.interval, offline_bars=a.offline_bars, offline_vix=a.offline_vix,
                       symbol=O.INDICES[a.index]["yahoo"])
    minutes = {"60m": 60, "15m": 15, "5m": 5}[a.interval]
    ctx = M.Context(bars, vix, minutes)
    rows = B.build_rows(ctx, cfg)
    warm, test, blocks = B.split_days(rows, cfg)
    known = {b.t.date() for b in bars}
    last = max(known)
    exit_of = {r["i"]: r["exit"] for r in rows}
    print("%s %s bars %s to %s: %d sessions, %d decision points. Learning-only: %s to %s (%d days). "
          "Test: %s to %s (%d days, %d blocks of %d)." % (
              a.index, a.interval, bars[0].t.date(), bars[-1].t.date(), len(known), len(rows), warm[0], warm[-1],
              len(warm), test[0], test[-1], len(test), len(blocks), cfg["block_days"]))

    # the learning models, refit for every block on the days before it, in parallel
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        ml_probs, stack_probs = {}, {}
        for kind, store in (("ml", ml_probs), ("stack", stack_probs)):
            for part in ex.map(B.fit_block, B.jobs(rows, blocks, cfg, kind)):
                store.update(part)
    print("Walk-forward models fitted (%d + %d predictions) in %.0f s." % (len(ml_probs), len(stack_probs),
                                                                         time.time() - t0))

    strategies = [(name, B.single_signals(rows, test, v)) for v, (name, _) in enumerate(M.VOTERS)]
    strategies.append(("Learning model (logistic)", B.prob_signals(rows, test, ml_probs, cfg, cfg["ml_band"])))
    strategies.append(("ALGO A: majority of 19", B.majority_signals(rows, test, cfg)))
    top, chosen = B.top_signals(rows, blocks, cfg)
    strategies.append(("ALGO B: best 5 on past data", top))
    strategies.append(("ALGO C: stacked probability", B.prob_signals(rows, test, stack_probs, cfg,
                                                                     cfg["theta"] - 0.5, cfg["agree"])))
    randoms = [("random-%d" % s, B.random_signals(rows, test, s)) for s in range(a.seeds)]

    results, rand_nets = {}, []
    with cf.ProcessPoolExecutor(max_workers=a.workers, initializer=B.init_sim,
                                initargs=(ctx, exit_of, cfg, known, last)) as ex:
        for name, trades, m in ex.map(B.run_sim, strategies + randoms, chunksize=4):
            if name.startswith("random-"):
                rand_nets.append(m["net"])
            else:
                results[name] = {"metrics": m, "trades": trades}
    rand_nets.sort()

    # report
    print("")
    print("Same-day %s option buying, one lot (%d), Rs %s paper capital, stop -%d%% / target +%d%% of premium, "
          "out by %s, at most one trade a day. Out-of-sample test years only." % (
              a.index, O.INDICES[a.index]["lot"], "{:,.0f}".format(cfg["capital"]), cfg["stop_pct"] * 100,
              cfg["target_pct"] * 100, cfg["exit_at"]))
    print("Random direction, %d runs: median %+.0f, 5th to 95th percentile %+.0f to %+.0f." % (
        len(rand_nets), statistics.median(rand_nets), rand_nets[int(0.05 * len(rand_nets))],
        rand_nets[min(len(rand_nets) - 1, int(0.95 * len(rand_nets)))]))
    print("")
    print("%-30s %6s %6s %6s %8s %8s %9s %10s %8s %7s" % ("method", "trades", "win%", "dir%", "avg win", "avg loss",
                                                       "per trade", "net", "max dd", "beats"))
    for name, r in sorted(results.items(), key=lambda kv: -kv[1]["metrics"]["net"]):
        m = r["metrics"]
        if not m["trades"]:
            print("%-30s %6d   (no trades)" % (name, 0))
            continue
        print("%-30s %6d %5.1f%% %5.1f%% %8.0f %8.0f %+9.0f %+10.0f %8.0f %6.0f%%%s" % (
            name, m["trades"], 100 * m["win_rate"], 100 * m["direction_right"], m["avg_win"], m["avg_loss"],
            m["expectancy"], m["net"], m["max_drawdown"], pct_beaten(m["net"], rand_nets),
            "  RAN OUT %s" % m["ruin"] if m["ruin"] else ""))
    print("")
    print("win% = trades that made money after costs; dir% = days the direction was right at the exit time;")
    print("beats = share of the random-direction runs this method's net beat. Charges and slippage included.")
    stack_rows = [r for r in rows if r["i"] in stack_probs]
    for lo, hi, word in ((0.60, 1.01, "p >= 0.60 (calls)"), (0.0, 0.40, "p <= 0.40 (puts)")):
        sel = [r for r in stack_rows if lo <= stack_probs[r["i"]] < hi]
        if sel:
            right = sum(1 for r in sel if (r["y"] == 1) == (lo >= 0.6))
            print("Stacked model calibration, %s: %d decision points, direction right %.1f%%." % (
                word, len(sel), 100.0 * right / len(sel)))
    if chosen:
        print("ALGO B's picks, latest blocks: " + "; ".join("%s: %s" % (d, ", ".join(v) or "none")
                                                         for d, v in chosen[-3:]))
    out = os.path.join(HERE, "results")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "backtest-%s-%s-%s.json" % (a.index.lower(), a.interval, datetime.date.today().isoformat()))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"config": cfg, "interval": a.interval, "test": [test[0].isoformat(), test[-1].isoformat()],
                   "random_nets": rand_nets, "algo_b_picks": chosen,
                   "results": {k: v for k, v in results.items()}}, fh, indent=1, default=str)
    print("Saved %s (%.0f s)." % (path, time.time() - t0))
    print("A backtest on estimated option prices is a filter, not a promise: real premiums, fills and "
          "news differ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
