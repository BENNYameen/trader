"""Live paper trading, same rules as the backtest: Algorithm B trades the paper account and
Donchian breakout keeps a shadow book, each watching NIFTY and SENSEX together.

- Decisions at the hourly closes 10:15, 11:15, 12:15, 13:15 and 14:15 (as in the backtest).
  A decision older than FRESH minutes when the tool sees it is logged as missed, never traded
  late. SENSEX on Yahoo runs about 15 minutes behind, so it gets more time.
- At most one trade a day per book: the index whose signal is stronger (more of Algorithm B's
  five indicators agreeing); a tie goes to NIFTY (live data). NIFTY and SENSEX move together:
  trading both would be one bet twice.
- Exit: premium -20 % (stop), +40 % (target) or 15:15, checked on 5-minute bars, stop first.
- Prices are Black-Scholes estimates from India VIX, like the backtest. Paper only."""

import concurrent.futures as cf
import datetime
import json
import os

from . import backtest as B
from . import data as D
from . import methods as M
from . import options as O

IST = datetime.timedelta(hours=5, minutes=30)
HOUR, FIVE = datetime.timedelta(hours=1), datetime.timedelta(minutes=5)
DECISIONS = [datetime.time(h, 15) for h in (10, 11, 12, 13, 14)]
EXIT = datetime.time(15, 15)
FRESH = {"NIFTY": 15, "SENSEX": 35}                 # minutes
INDEXES = ("NIFTY", "SENSEX")
BOOKS = (("algo_b", "ALGO B (trades the account)"), ("donchian", "Donchian breakout (shadow)"))
DON = [n for n, _ in M.VOTERS].index("Donchian breakout")
CFG = dict(B.DEFAULTS)


def now_ist():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None, microsecond=0) + IST


# ---------------------------------------------------------------- data: live, or a past day replayed

class LiveData(object):
    """History from the daily cache (days before today); today's bars fetched fresh each tick."""

    def __init__(self):
        self._hist, self._vix = {}, None

    def history(self, index, day):
        if index not in self._hist:
            bars, vix = D.load("60m", symbol=O.INDICES[index]["yahoo"])
            self._hist[index], self._vix = [b for b in bars if b.t.date() < day], vix
        return self._hist[index], self._vix

    def today(self, now):
        """{index: (hourly bars, 5-minute bars)} complete by now, and the latest India VIX."""
        jobs = [(ix, m) for ix in INDEXES for m in (60, 5)]
        out = {}
        with cf.ThreadPoolExecutor(max_workers=5) as ex:      # the five downloads at once
            futs = {ex.submit(D.today_bars, O.INDICES[ix]["yahoo"], m, now): (ix, m) for ix, m in jobs}
            vix_f = ex.submit(D.today_bars, "^INDIAVIX", 5, now)
            for f, (ix, m) in futs.items():
                bars = [b for b in f.result()[0] if b.t.date() == now.date()]
                out.setdefault(ix, {})[m] = bars
            vix_bars = [b for b in vix_f.result()[0] if b.t.date() == now.date()]
        return {ix: (out[ix][60], out[ix][5]) for ix in INDEXES}, (vix_bars[-1].c if vix_bars else None)


class ReplayData(object):
    """A past day, cut at each simulated moment: only bars complete by then are visible."""

    def __init__(self, day):
        self.day, self._h, self._f = day, {}, {}
        for ix in INDEXES:
            sym = O.INDICES[ix]["yahoo"]
            self._h[ix] = D.bars_from(D.chart(sym, "730d", "60m"), 60)
            self._f[ix] = [b for b in D.bars_from(D.chart(sym, "60d", "5m"), 5) if b.t.date() == day]
        self._vix = D.daily_closes(D.chart("^INDIAVIX", "5y", "1d"))
        self._vix5 = [b for b in D.bars_from(D.chart("^INDIAVIX", "60d", "5m"), 5) if b.t.date() == day]
        if not self._f["NIFTY"]:
            raise D.DataError("no 5-minute NIFTY bars for %s (Yahoo keeps about 60 days)" % day)

    def history(self, index, day):
        return [b for b in self._h[index] if b.t.date() < day], self._vix

    def today(self, now):
        def cut(bars, step):
            return [b for b in bars if b.t.date() == now.date() and b.t + step <= now]
        out = {ix: (cut(self._h[ix], HOUR), cut(self._f[ix], FIVE)) for ix in INDEXES}
        v = cut(self._vix5, FIVE)
        return out, (v[-1].c if v else None)


# ---------------------------------------------------------------- the signals

class Brain(object):
    """One index on one day: Algorithm B's five indicators, chosen on all the days before today."""

    def __init__(self, index, hist_bars, vix_daily, cfg=CFG):
        self.index, self.hist, self.vix = index, hist_bars, vix_daily
        rows = B.build_rows(M.Context(hist_bars, vix_daily, 60), cfg)
        self.top = B.top_voters(rows, cfg)
        self.top_names = [M.VOTERS[v][0] for v in self.top]

    def votes_at(self, today_hourly, decision_end):
        """The 19 votes at the hourly bar that closes at decision_end (None if it is not in yet)."""
        today = [b for b in today_hourly if b.t + HOUR <= decision_end]
        if not today or today[-1].t + HOUR != decision_end:
            return None, None
        bars = self.hist + today
        ctx = M.Context(bars, self.vix, 60)
        return M.votes(ctx, len(bars) - 1), bars[-1].c

    def signal(self, book, v):
        """(direction, strength) for a book from the votes."""
        if book == "donchian":
            return v[DON], 1
        up = sum(1 for k in self.top if v[k] > 0)
        dn = sum(1 for k in self.top if v[k] < 0)
        if len(self.top) >= CFG["top_agree"] and up >= CFG["top_agree"]:
            return 1, up
        if len(self.top) >= CFG["top_agree"] and dn >= CFG["top_agree"]:
            return -1, dn
        return 0, max(up, dn)


# ---------------------------------------------------------------- the ledger

def new_ledger(cash, start):
    return {"created_by": "options-ensemble paper", "start": start, "start_cash": float(cash),
            "rules": RULES, "books": {k: {"name": n, "cash": float(cash), "trades": []} for k, n in BOOKS},
            "days": {}}


RULES = [
    "Paper only: Black-Scholes prices from India VIX, nothing is sent to any broker.",
    "Algorithm B trades the account: every day it ranks the 19 indicators on all past days and keeps the "
    "best 5; a trade needs 4 of the 5 to agree. Donchian breakout keeps a shadow book for comparison.",
    "Decisions at 10:15, 11:15, 12:15, 13:15, 14:15; at most one trade a day per book, NIFTY or SENSEX.",
    "One lot (NIFTY 65, SENSEX 20), nearest weekly expiry with a day left; the strike nearest the money "
    "whose loss at the stop fits Rs 1,500.",
    "Exit at premium -20 %, +40 % or 15:15, whichever first; stop checked first; Zerodha charges and Rs 0.50 "
    "a unit slippage each side.",
]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- one tick

def _known_days(brains):
    days = set()
    for br in brains.values():
        days.update(b.t.date() for b in br.hist)
    return days


def enter(ledger, book, day_key, index, d, strength, brain, spot, decision_end, vix, known, log):
    bk = ledger["books"][book]
    kind = "CE" if d > 0 else "PE"
    expiry = O.next_expiry(decision_end.date(), known | {decision_end.date()}, decision_end.date(), index)
    lot = O.lot_for(index, expiry)
    vol = (vix or 15.0) / 100
    pick = O.choose_strike(spot, O.years_to(decision_end, expiry), vol, kind, CFG["max_loss"], CFG["stop_pct"],
                           bk["cash"], CFG["slip"], index, lot)
    if pick is None:
        log("%s: %s %s signal at %s, but no strike fits the Rs %d risk limit: skipped."
            % (bk["name"], index, kind, decision_end.strftime("%H:%M"), CFG["max_loss"]))
        return False
    strike, p0 = pick
    t = {"id": "%s-%s" % (day_key, book), "book": book, "date": day_key, "index": index, "side": kind,
         "strike": strike, "expiry": expiry.isoformat(), "lot": lot, "decision": decision_end.strftime("%H:%M"),
         "spot": round(spot, 2), "vix": round(vol * 100, 2), "entry": round(p0, 2),
         "stop": round(p0 * (1 - CFG["stop_pct"]), 2), "target": round(p0 * (1 + CFG["target_pct"]), 2),
         "strength": strength, "top5": brain.top_names if book == "algo_b" else ["Donchian breakout"],
         "status": "open"}
    bk["trades"].append(t)
    log("%s: BUY %s %d %s (%s expiry), 1 lot of %d at Rs %.2f (Rs %s), %s at %s. Stop Rs %.2f, target Rs %.2f."
        % (bk["name"], index, strike, kind, expiry.strftime("%d %b"), lot, p0, "{:,.0f}".format(p0 * lot),
           "%d of 5 agree" % strength if book == "algo_b" else "breakout", decision_end.strftime("%H:%M"),
           t["stop"], t["target"]))
    return True


def manage(ledger, t, five, now, log):
    """Walk the 5-minute bars since the entry: stop, target or 15:15."""
    if t["status"] != "open":
        return
    expiry = datetime.date.fromisoformat(t["expiry"])
    vol, slip = t["vix"] / 100, CFG["slip"]
    start = datetime.datetime.combine(datetime.date.fromisoformat(t["date"]),
                                      datetime.datetime.strptime(t["decision"], "%H:%M").time())
    res, last = None, None
    for b in five:
        end = b.t + FIVE
        if b.t < start or end > now:
            continue
        p_open = O.price(b.o, t["strike"], O.years_to(b.t, expiry), vol, t["side"]) - slip
        if p_open <= t["stop"]:
            res = ("stop", p_open, end)
            break
        worst, best = (b.l, b.h) if t["side"] == "CE" else (b.h, b.l)
        y = O.years_to(end, expiry)
        if O.price(worst, t["strike"], y, vol, t["side"]) - slip <= t["stop"]:
            res = ("stop", t["stop"], end)
            break
        if O.price(best, t["strike"], y, vol, t["side"]) - slip >= t["target"]:
            res = ("target", t["target"], end)
            break
        last = (b, end, y)
        if end.time() >= EXIT:
            res = ("time", O.price(b.c, t["strike"], y, vol, t["side"]) - slip, end)
            break
    late = now.time() >= (datetime.time(15, 45) if t["index"] == "SENSEX" else datetime.time(15, 25))
    if res is None and late and last:               # the 15:10 bar never came: out at the last one
        b, end, y = last
        res = ("time", O.price(b.c, t["strike"], y, vol, t["side"]) - slip, end)
    if res is None:
        return
    reason, p1, end = res
    p1 = max(0.05, p1)
    lot = t["lot"]
    gross = (p1 - t["entry"]) * lot
    cost = O.charges(t["entry"] * lot, p1 * lot, t["index"])
    bk = ledger["books"][t["book"]]
    bk["cash"] = round(bk["cash"] + gross - cost, 2)
    t.update(status="closed", exit=round(p1, 2), exit_time=end.strftime("%H:%M"), reason=reason,
             gross=round(gross, 2), charges=cost, net=round(gross - cost, 2), cash_after=bk["cash"])
    log("%s: SELL %s %d %s at Rs %.2f (%s, %s). P&L Rs %+.2f, charges Rs %.2f, net Rs %+.2f. Book Rs %s."
        % (bk["name"], t["index"], t["strike"], t["side"], p1, {"stop": "STOP", "target": "TARGET",
                                                                "time": "15:15 exit"}[reason],
           end.strftime("%H:%M"), gross, cost, gross - cost, "{:,.2f}".format(bk["cash"])))


def tick(ledger, data, now, brains, live=True, log=print):
    """One pass: new entries at due decisions, then exits. Returns True when the day is done."""
    day = now.date()
    key = day.isoformat()
    if key < ledger.get("start", key):
        return True                                   # the month has not started: nothing to log
    if not O.is_trading_day(day, set(), day - datetime.timedelta(days=1)) or now.time() < datetime.time(9, 15):
        return now.time() >= datetime.time(15, 50)
    for ix in INDEXES:
        if ix not in brains:
            hist, vix = data.history(ix, day)
            brains[ix] = Brain(ix, hist, vix)
    today, vix_now = data.today(now)
    known = _known_days(brains)
    days = ledger["days"].setdefault(key, {})
    for book, _ in BOOKS:
        st = days.setdefault(book, {"checked": [], "missed": [], "status": "waiting"})
        if any(t["date"] == key for t in ledger["books"][book]["trades"]):
            continue
        for dt in DECISIONS:
            label = dt.strftime("%H:%M")
            end = datetime.datetime.combine(day, dt)
            if label in st["checked"] or label in st["missed"] or end > now:
                continue
            age = (now - end).total_seconds() / 60
            cands, waiting, seen = [], False, 0
            for ix in INDEXES:
                if live and age > FRESH[ix]:
                    continue                          # too old to act on: never trade a signal late
                v, spot = brains[ix].votes_at(today[ix][0], end)
                if v is None:
                    waiting = waiting or age <= FRESH[ix]   # its bar is not in yet (SENSEX lags)
                    continue
                seen += 1
                d, strength = brains[ix].signal(book, v)
                if d:
                    cands.append((strength, -INDEXES.index(ix), ix, d, spot))
            if cands:
                strength, _, ix, d, spot = max(cands)
                st["checked"].append(label)
                if enter(ledger, book, key, ix, d, strength, brains[ix], spot, end, vix_now, known, log):
                    st["status"] = "traded"
                    break
            elif waiting:
                continue                              # look again next tick
            elif seen == 0 and live:
                st["missed"].append(label)            # the tool was not running in time
            else:
                st["checked"].append(label)
    for book, _ in BOOKS:
        for t in ledger["books"][book]["trades"]:
            if t["date"] == key and t["status"] == "open":
                manage(ledger, t, today[t["index"]][1], now, log)
    for book, _ in BOOKS:
        st = days[book]
        if st["status"] == "waiting" and len(st["checked"]) + len(st["missed"]) >= len(DECISIONS):
            st["status"] = "missed" if st["missed"] and not st["checked"] else "no signal"
    open_today = any(t["date"] == key and t["status"] == "open" for b, _ in BOOKS for t in ledger["books"][b]["trades"])
    resolved = all(days[b]["status"] != "waiting" for b, _ in BOOKS)
    return now.time() >= datetime.time(15, 50) or (resolved and not open_today)


def score(ledger):
    out = {}
    for book, name in BOOKS:
        tr = [t for t in ledger["books"][book]["trades"] if t["status"] == "closed"]
        nets = [t["net"] for t in tr]
        peak = eq = ledger["start_cash"]
        dd = 0.0
        for x in nets:
            eq += x
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        wins = [x for x in nets if x > 0]
        out[book] = {"name": name, "trades": len(tr), "wins": len(wins), "losses": len(nets) - len(wins),
                     "net": round(sum(nets), 2), "charges": round(sum(t["charges"] for t in tr), 2),
                     "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
                     "avg_loss": round(sum(x for x in nets if x <= 0) / max(1, len(nets) - len(wins)), 2),
                     "max_drawdown": round(dd, 2), "balance": ledger["books"][book]["cash"],
                     "open": [t["id"] for t in ledger["books"][book]["trades"] if t["status"] == "open"],
                     "days": {s: sum(1 for d in ledger["days"].values() if d.get(book, {}).get("status") == s)
                              for s in ("traded", "no signal", "missed")}}
    return out
