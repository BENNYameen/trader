"""The methods: each one looks at the bars up to now and votes +1 (up), -1 (down) or 0.

Standard textbook settings, fixed in advance (nothing here is tuned to the test
data). Momentum-style rules follow the move; reversion-style rules fade it."""

import datetime

from . import indicators as ind


class Context(object):
    """Every indicator, computed once over the whole series, each value from past bars only."""

    def __init__(self, bars, vix_by_date, minutes):
        self.bars, self.minutes = bars, minutes
        c = [b.c for b in bars]
        self.c = c
        self.ema9, self.ema21, self.ema50 = ind.ema(c, 9), ind.ema(c, 21), ind.ema(c, 50)
        self.sma20, self.sma50 = ind.sma(c, 20), ind.sma(c, 50)
        self.rsi = ind.rsi(c, 14)
        self.macdh = ind.macd_hist(c)
        self.st = ind.supertrend(bars, 10, 3.0)
        self.bb_mid, self.bb_up, self.bb_lo = ind.bollinger(c, 20, 2.0)
        self.k, self.d = ind.stochastic(bars, 14, 3)
        self.adx, self.pdi, self.mdi = ind.adx(bars, 14)
        self.cci = ind.cci(bars, 20)
        self.wr = ind.williams_r(bars, 14)
        self.don_up, self.don_lo = ind.donchian_prev(bars, 20)
        self.roc = ind.roc(c, 10)
        self.ha = ind.heikin_ashi(bars)
        self.psar = ind.psar(bars)
        self.twap = ind.session_twap(bars)
        self.atr = ind.atr(bars, 14)
        self.atr_avg = ind.sma(self.atr, 50)
        # the day's opening range (first 15 minutes; the first hour on hourly bars), its running
        # high and low, the day's open and the previous day's close
        self.or_hi, self.or_lo, self.day_hi, self.day_lo, self.day_open, self.prev_close = [], [], [], [], [], []
        or_end = datetime.time(9, 30) if minutes < 60 else datetime.time(10, 15)
        day, ohi, olo, dhi, dlo, dop, pc, last_close = None, None, None, None, None, None, None, None
        for b in bars:
            if b.t.date() != day:
                day, ohi, olo, dhi, dlo, dop, pc = b.t.date(), None, None, b.h, b.l, b.o, last_close
            dhi, dlo = max(dhi, b.h), min(dlo, b.l)
            if (b.t + datetime.timedelta(minutes=minutes)).time() <= or_end:
                ohi = b.h if ohi is None else max(ohi, b.h)
                olo = b.l if olo is None else min(olo, b.l)
            self.or_hi.append(ohi), self.or_lo.append(olo)
            self.day_hi.append(dhi), self.day_lo.append(dlo)
            self.day_open.append(dop), self.prev_close.append(pc)
            last_close = b.c
        dates = sorted(vix_by_date)
        self.vix_prev = []
        j, last = 0, None
        for b in bars:                    # yesterday's VIX close: nothing from today
            while j < len(dates) and dates[j] < b.t.date():
                last = vix_by_date[dates[j]]
                j += 1
            self.vix_prev.append(last)


def _sign(x, lo=0.0):
    return 1 if x > lo else -1 if x < -lo else 0


# ---------------------------------------------------------------- the voters

def ema_cross(x, i):
    return 1 if x.ema9[i] > x.ema21[i] and x.c[i] > x.ema9[i] else -1 if x.ema9[i] < x.ema21[i] and x.c[i] < x.ema9[i] else 0


def sma_cross(x, i):
    return _sign(x.sma20[i] - x.sma50[i])


def ema50_trend(x, i):
    rising = i >= 3 and x.ema50[i] > x.ema50[i - 3]
    falling = i >= 3 and x.ema50[i] < x.ema50[i - 3]
    return 1 if x.c[i] > x.ema50[i] and rising else -1 if x.c[i] < x.ema50[i] and falling else 0


def rsi_momentum(x, i):
    return 1 if x.rsi[i] > 55 else -1 if x.rsi[i] < 45 else 0


def rsi_reversion(x, i):
    return 1 if x.rsi[i] < 30 else -1 if x.rsi[i] > 70 else 0


def macd(x, i):
    if i < 1:
        return 0
    h, p = x.macdh[i], x.macdh[i - 1]
    return 1 if h > 0 and h > p else -1 if h < 0 and h < p else 0


def supertrend(x, i):
    return x.st[i]


def bollinger_breakout(x, i):
    return 1 if x.c[i] > x.bb_up[i] else -1 if x.c[i] < x.bb_lo[i] else 0


def bollinger_reversion(x, i):
    return -bollinger_breakout(x, i)


def stochastic(x, i):
    return 1 if x.k[i] < 20 and x.k[i] > x.d[i] else -1 if x.k[i] > 80 and x.k[i] < x.d[i] else 0


def adx_dmi(x, i):
    if x.adx[i] < 20:
        return 0
    return _sign(x.pdi[i] - x.mdi[i])


def cci(x, i):
    return 1 if x.cci[i] > 100 else -1 if x.cci[i] < -100 else 0


def williams_r(x, i):
    return 1 if x.wr[i] < -80 else -1 if x.wr[i] > -20 else 0


def donchian(x, i):
    if x.don_up[i] is None:
        return 0
    return 1 if x.c[i] > x.don_up[i] else -1 if x.c[i] < x.don_lo[i] else 0


def roc(x, i):
    return _sign(x.roc[i], 0.1)


def orb(x, i):
    if x.or_hi[i] is None or (x.bars[i].t + datetime.timedelta(minutes=x.minutes)).time() <= (
            datetime.time(9, 30) if x.minutes < 60 else datetime.time(10, 15)):
        return 0
    return 1 if x.c[i] > x.or_hi[i] else -1 if x.c[i] < x.or_lo[i] else 0


def twap(x, i):
    if i < 1 or x.bars[i - 1].t.date() != x.bars[i].t.date():
        return 0
    up = x.twap[i] > x.twap[i - 1]
    return 1 if x.c[i] > x.twap[i] and up else -1 if x.c[i] < x.twap[i] and not up else 0


def heikin_ashi(x, i):
    return x.ha[i]


def psar(x, i):
    return x.psar[i]


VOTERS = [
    ("EMA 9/21 cross", ema_cross), ("SMA 20/50 cross", sma_cross), ("EMA 50 trend", ema50_trend),
    ("RSI momentum", rsi_momentum), ("RSI reversion", rsi_reversion), ("MACD", macd), ("Supertrend", supertrend),
    ("Bollinger breakout", bollinger_breakout), ("Bollinger reversion", bollinger_reversion),
    ("Stochastic", stochastic), ("ADX/DMI", adx_dmi), ("CCI", cci), ("Williams %R", williams_r),
    ("Donchian breakout", donchian), ("Rate of change", roc), ("Opening range", orb), ("Session average", twap),
    ("Heikin-Ashi", heikin_ashi), ("Parabolic SAR", psar),
]


def votes(x, i):
    return [f(x, i) for _, f in VOTERS]


def features(x, i):
    """Raw inputs for the learning model, all from bars up to i."""
    c = x.c[i]

    def ret(n):
        return c / x.c[i - n] - 1 if i >= n else 0.0
    rng = x.day_hi[i] - x.day_lo[i]
    t = x.bars[i].t
    minutes = (t.hour - 9) * 60 + t.minute - 15 + x.minutes
    return [
        ret(1), ret(3), ret(6),
        c / x.ema9[i] - 1, c / x.ema21[i] - 1, c / x.ema50[i] - 1,
        x.rsi[i] / 100 - 0.5, x.macdh[i] / c,
        ((c - x.day_lo[i]) / rng - 0.5) if rng else 0.0,
        (x.day_open[i] / x.prev_close[i] - 1) if x.prev_close[i] else 0.0,
        minutes / 375.0,
        (x.atr[i] / x.atr_avg[i] - 1) if x.atr_avg[i] else 0.0,
        (x.vix_prev[i] or 15.0) / 100,
        x.adx[i] / 100, max(-3.0, min(3.0, x.cci[i] / 100)), x.roc[i] / 100,
    ]
