"""Walk-forward backtest: every method alone, three ways of combining them, and random
direction as the yardstick. One same-day NIFTY option trade a day at most, bought on paper.

Honesty rules built in:
  - indicators use past bars only; the VIX used is yesterday's close
  - the learning models and the indicator ranking are refit every block of days on the days
    BEFORE the block, and only then judged on the block (walk-forward, out of sample)
  - the strategies' settings are fixed before the test; nothing is tuned on the test years
  - inside a bar the stop is checked before the target; a gap through the stop fills at the gap
  - costs: Zerodha's option charges plus a slippage per unit on each side"""

import datetime
import random

from . import methods as M
from . import options as O
from .ml import Logit

DEFAULTS = {
    "index": "NIFTY",        # or SENSEX
    "capital": 15000.0,      # paper rupees
    "max_loss": 1500.0,      # the loss at the premium stop must fit this (10 % of capital)
    "stop_pct": 0.20,        # out when the premium falls 20 %
    "target_pct": 0.40,      # out when it rises 40 %
    "slip": 0.5,             # rupees a unit, each side
    "entry_from": "09:30", "entry_to": "14:30", "exit_at": "15:15",
    "warmup_days": 230,      # trading days used only for training before the test starts
    "block_days": 20,        # refit every 20 trading days
    "min_train_rows": 300,
    "ml_band": 0.05,         # the learning model votes when p > 0.55 or p < 0.45
    "theta": 0.60,           # the stacked model trades when p >= 0.60 (calls) or <= 0.40 (puts)
    "agree": 3,              # ... and the votes lean its way by at least 3
    "majority": 5,           # majority vote: up votes minus down votes at least 5 (of 19)
    "top_k": 5, "top_agree": 4, "top_min_votes": 100, "top_min_hit": 0.52,
}


def _t(s):
    h, m = s.split(":")
    return datetime.time(int(h), int(m))


# ---------------------------------------------------------------- the rows

def build_rows(ctx, cfg):
    """One row per decision bar: its votes, features and label (1 when NIFTY closes the exit
    bar higher than the decision bar's close). Days without an exit bar are left out."""
    step = datetime.timedelta(minutes=ctx.minutes)
    lo, hi, ex = _t(cfg["entry_from"]), _t(cfg["entry_to"]), _t(cfg["exit_at"])
    exit_idx = {}
    for i, b in enumerate(ctx.bars):
        if (b.t + step).time() == ex:
            exit_idx[b.t.date()] = i
    rows = []
    for i, b in enumerate(ctx.bars):
        end = (b.t + step).time()
        day = b.t.date()
        if not lo <= end <= hi or day not in exit_idx or exit_idx[day] <= i or i < 60:
            continue
        rows.append({"i": i, "day": day, "votes": M.votes(ctx, i), "x": M.features(ctx, i),
                     "y": 1 if ctx.c[exit_idx[day]] > ctx.c[i] else 0, "exit": exit_idx[day]})
    return rows


def split_days(rows, cfg):
    days = sorted({r["day"] for r in rows})
    w = min(cfg["warmup_days"], max(1, len(days) // 2))
    test = days[w:]
    blocks = [test[k:k + cfg["block_days"]] for k in range(0, len(test), cfg["block_days"])]
    return days[:w], test, blocks


# ---------------------------------------------------------------- walk-forward models

def fit_block(job):
    """(kind, train rows, test rows) -> {row index: probability}. kind 'ml' learns from the
    features, 'stack' from the 19 votes. Module level so it can run in another process."""
    kind, train, test = job
    key = "x" if kind == "ml" else "votes"
    model = Logit(l2=1e-3, lr=0.5, epochs=150).fit([r[key] for r in train], [r["y"] for r in train])
    return {r["i"]: model.prob(r[key]) for r in test}


def jobs(rows, blocks, cfg, kind):
    out = []
    for blk in blocks:
        start, days = blk[0], set(blk)
        train = [r for r in rows if r["day"] < start]
        if len(train) < cfg["min_train_rows"]:
            continue
        out.append((kind, train, [r for r in rows if r["day"] in days]))
    return out


def top_voters(train, cfg):
    """The voters with the best hit rate on the training rows (enough votes, better than 52 %)."""
    scored = []
    for v in range(len(M.VOTERS)):
        n = hits = 0
        for r in train:
            s = r["votes"][v]
            if s:
                n += 1
                hits += (s > 0) == (r["y"] == 1)
        if n >= cfg["top_min_votes"] and hits / n >= cfg["top_min_hit"]:
            scored.append((hits / n, v))
    return [v for _, v in sorted(scored, reverse=True)[:cfg["top_k"]]]


# ---------------------------------------------------------------- signals: {day: (row index, direction)}

def first_signal(rows, test_days, pick):
    days, out = set(test_days), {}
    for r in rows:
        if r["day"] in days and r["day"] not in out:
            d = pick(r)
            if d:
                out[r["day"]] = (r["i"], d)
    return out


def single_signals(rows, test_days, v):
    return first_signal(rows, test_days, lambda r: r["votes"][v])


def majority_signals(rows, test_days, cfg):
    return first_signal(rows, test_days,
                        lambda r: 1 if sum(r["votes"]) >= cfg["majority"] else -1 if sum(r["votes"]) <= -cfg["majority"] else 0)


def prob_signals(rows, test_days, probs, cfg, band, agree=0):
    def pick(r):
        p = probs.get(r["i"])
        if p is None:
            return 0
        net = sum(r["votes"])
        if p >= 0.5 + band and net >= agree:
            return 1
        if p <= 0.5 - band and net <= -agree:
            return -1
        return 0
    return first_signal(rows, test_days, pick)


def top_signals(rows, blocks, cfg):
    out, chosen = {}, []
    for blk in blocks:
        train = [r for r in rows if r["day"] < blk[0]]
        top = top_voters(train, cfg)
        chosen.append((blk[0].isoformat(), [M.VOTERS[v][0] for v in top]))
        if len(top) < cfg["top_agree"]:
            continue

        def pick(r, top=top):
            up = sum(1 for v in top if r["votes"][v] > 0)
            dn = sum(1 for v in top if r["votes"][v] < 0)
            return 1 if up >= cfg["top_agree"] else -1 if dn >= cfg["top_agree"] else 0
        out.update(first_signal(rows, blk, pick))
    return out, chosen


def random_signals(rows, test_days, seed):
    rng, out, days = random.Random(seed), {}, set(test_days)
    for r in rows:
        if r["day"] in days and r["day"] not in out:
            out[r["day"]] = (r["i"], rng.choice((1, -1)))
    return out


# ---------------------------------------------------------------- the trade

def simulate(ctx, exit_of, signals, cfg, known_days, last_known):
    """Paper-trade the signals in date order with one lot each; returns (trades, skipped, ruin_day)."""
    step = datetime.timedelta(minutes=ctx.minutes)
    equity, trades, skipped, ruin = cfg["capital"], [], 0, None
    slip, sp, tp = cfg["slip"], cfg["stop_pct"], cfg["target_pct"]
    index = cfg.get("index", "NIFTY")
    for day in sorted(signals):
        i, d = signals[day]
        kind = "CE" if d > 0 else "PE"
        b0 = ctx.bars[i]
        expiry = O.next_expiry(day, known_days, last_known, index)
        lot = O.lot_for(index, expiry)
        vol = (ctx.vix_prev[i] or 15.0) / 100
        pick = O.choose_strike(b0.c, O.years_to(b0.t + step, expiry), vol, kind, cfg["max_loss"], sp,
                               equity, slip, index, lot)
        if pick is None:
            skipped += 1
            continue
        strike, p0 = pick
        stop, target = p0 * (1 - sp), p0 * (1 + tp)
        res = None
        for k in range(i + 1, exit_of[i] + 1):
            b = ctx.bars[k]
            t_end = b.t + step
            y_open, y_end = O.years_to(b.t, expiry), O.years_to(t_end, expiry)
            p_open = O.price(b.o, strike, y_open, vol, kind) - slip
            if p_open <= stop:
                res = ("stop", p_open, t_end)          # a gap through the stop fills at the gap
                break
            worst, best = (b.l, b.h) if kind == "CE" else (b.h, b.l)
            if O.price(worst, strike, y_end, vol, kind) - slip <= stop:
                res = ("stop", stop, t_end)
                break
            if O.price(best, strike, y_end, vol, kind) - slip >= target:
                res = ("target", target, t_end)
                break
            if k == exit_of[i]:
                res = ("time", O.price(b.c, strike, y_end, vol, kind) - slip, t_end)
        if res is None:
            skipped += 1
            continue
        reason, p1, t1 = res
        p1 = max(p1, 0.05)
        gross = (p1 - p0) * lot
        cost = O.charges(p0 * lot, p1 * lot, index)
        net = gross - cost
        equity += net
        trades.append({"day": day.isoformat(), "time": (b0.t + step).strftime("%H:%M"), "side": kind,
                       "strike": strike, "expiry": expiry.isoformat(), "entry": round(p0, 2), "exit": round(p1, 2),
                       "reason": reason, "exit_time": t1.strftime("%H:%M"), "gross": round(gross, 2),
                       "charges": cost, "net": round(net, 2), "equity": round(equity, 2), "dir": d,
                       "right": (ctx.c[exit_of[i]] > b0.c) == (d > 0)})
        if equity < 1500:
            ruin = day.isoformat()
            break
    return trades, skipped, ruin


_G = {}


def init_sim(ctx, exit_of, cfg, known_days, last_known):
    """Each worker process keeps one copy of the data (set once, not sent with every job)."""
    _G.update(ctx=ctx, exit_of=exit_of, cfg=cfg, known=known_days, last=last_known)


def run_sim(item):
    name, signals = item
    trades, skipped, ruin = simulate(_G["ctx"], _G["exit_of"], signals, _G["cfg"], _G["known"], _G["last"])
    return name, trades, metrics(trades, skipped, ruin, _G["cfg"]["capital"])


def metrics(trades, skipped, ruin, capital):
    n = len(trades)
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    peak, eq, dd, dd_pct = capital, capital, 0.0, 0.0
    for x in nets:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
        dd_pct = min(dd_pct, (eq - peak) / peak if peak else 0)
    return {
        "trades": n, "skipped": skipped, "ruin": ruin,
        "win_rate": round(len(wins) / n, 4) if n else None,
        "direction_right": round(sum(1 for t in trades if t["right"]) / n, 4) if n else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "expectancy": round(sum(nets) / n, 2) if n else 0.0,
        "net": round(sum(nets), 2), "final": round(capital + sum(nets), 2),
        "max_drawdown": round(dd, 2), "max_drawdown_pct": round(100 * dd_pct, 1),
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "charges": round(sum(t["charges"] for t in trades), 2),
        "exits": {k: sum(1 for t in trades if t["reason"] == k) for k in ("target", "stop", "time")},
    }
