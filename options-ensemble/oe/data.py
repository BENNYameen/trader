"""NIFTY and India VIX bars from Yahoo's free chart endpoint, in India time, cached on disk.

Yahoo keeps about 60 days of 5-minute bars and about 3 years of hourly bars for
^NSEI. The index has no volume. Data is unofficial and can lag; the cache keeps
one copy a day so a backtest does not hit Yahoo again and again."""

import collections
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; options-ensemble/0.1; personal research)"
IST = datetime.timedelta(hours=5, minutes=30)
EPOCH = datetime.datetime(1970, 1, 1)
OPEN, CLOSE = datetime.time(9, 15), datetime.time(15, 30)
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

Bar = collections.namedtuple("Bar", "t o h l c")   # t = bar start, naive India time


class DataError(Exception):
    pass


def _get(url):
    last = None
    for host in ("query2", "query1"):
        try:
            req = urllib.request.Request(url.replace("://query2.", "://%s." % host),
                                         headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            last = e
    raise DataError("Yahoo did not answer: %s" % last)


def chart(sym, rng, interval, cache=CACHE, offline=None):
    """Yahoo chart JSON (dict), cached per symbol, range, interval and day."""
    if offline:
        with open(offline, encoding="utf-8") as fh:
            return json.load(fh)
    os.makedirs(cache, exist_ok=True)
    name = "%s_%s_%s_%s.json" % (sym.replace("^", ""), rng, interval, datetime.date.today().isoformat())
    path = os.path.join(cache, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (
        urllib.parse.quote(sym), rng, interval)
    doc = json.loads(_get(url))
    if not (doc.get("chart") or {}).get("result"):
        raise DataError("no data for %s %s %s" % (sym, rng, interval))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return doc


def bars_from(doc, minutes, now=None):
    """Chart JSON -> session bars (9:15 to 15:30 India time) on the interval's grid,
    complete by `now` (naive India time; default: the data's own time)."""
    res = doc["chart"]["result"][0]
    q = (res.get("indicators") or {}).get("quote", [{}])[0]
    meta = res.get("meta") or {}
    rmt = meta.get("regularMarketTime")
    as_of = now or (EPOCH + datetime.timedelta(seconds=rmt) + IST if rmt else datetime.datetime.max)
    step = datetime.timedelta(minutes=minutes)
    out = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        vals = []
        for k in ("open", "high", "low", "close"):
            arr = q.get(k) or []
            vals.append(arr[i] if i < len(arr) else None)
        if ts is None or None in vals:
            continue
        t = EPOCH + datetime.timedelta(seconds=int(ts)) + IST
        if not OPEN <= t.time() < CLOSE:
            continue
        if minutes < 60 and (t.minute % minutes or t.second):
            continue
        if minutes >= 60 and (t.minute != 15 or t.second):
            continue                      # NSE hourly bars start at :15
        end = min(t + step, datetime.datetime.combine(t.date(), CLOSE))
        if end > as_of:
            continue                      # still forming
        o, h, l, c = (float(v) for v in vals)
        out[t] = Bar(t, o, max(h, o, c), min(l, o, c), c)
    return [out[k] for k in sorted(out)]


def daily_closes(doc):
    """Daily chart JSON -> {date: close} (India dates)."""
    res = doc["chart"]["result"][0]
    closes = (res.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    out = {}
    for ts, c in zip(res.get("timestamp") or [], closes):
        if ts is not None and c is not None:
            out[(EPOCH + datetime.timedelta(seconds=int(ts)) + IST).date()] = float(c)
    return out


def load(interval="60m", cache=CACHE, offline_bars=None, offline_vix=None, symbol="^NSEI"):
    """(bars, vix_by_date) for an index (^NSEI NIFTY, ^BSESN SENSEX): interval 60m (about 3
    years) or 5m (about 60 days). India VIX stands in for SENSEX volatility too."""
    minutes = {"60m": 60, "5m": 5, "15m": 15}[interval]
    rng = {"60m": "730d", "5m": "60d", "15m": "60d"}[interval]
    bars = bars_from(chart(symbol, rng, interval, cache, offline_bars), minutes)
    vix = daily_closes(chart("^INDIAVIX", "5y", "1d", cache, offline_vix))
    if not bars:
        raise DataError("no bars for %s" % symbol)
    return bars, vix


def today_bars(symbol, minutes, now=None):
    """Today's bars, fetched fresh (no cache): the live view during the session."""
    interval = "%dm" % minutes
    doc = json.loads(_get("https://query2.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=%s" % (
        urllib.parse.quote(symbol), interval)))
    if not (doc.get("chart") or {}).get("result"):
        raise DataError("no data for %s today" % symbol)
    return bars_from(doc, minutes, now), doc["chart"]["result"][0].get("meta") or {}
