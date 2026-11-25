"""Indicators computed bar by bar from the past only (value i uses bars 0..i)."""


def ema(xs, n):
    out, k, v = [], 2.0 / (n + 1), None
    for x in xs:
        v = x if v is None else v + k * (x - v)
        out.append(v)
    return out


def sma(xs, n):
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / min(i + 1, n))
    return out


def rsi(closes, n=14):
    """Wilder's RSI; 50 until there is enough history."""
    out, ag, al = [], None, None
    for i, c in enumerate(closes):
        if i == 0:
            out.append(50.0)
            continue
        ch = c - closes[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if ag is None:
            ag, al = g, l
        else:
            ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
        out.append(50.0 if i < n else (100.0 if al == 0 else 100 - 100 / (1 + ag / al)))
    return out


def macd_hist(closes, fast=12, slow=26, signal=9):
    line = [a - b for a, b in zip(ema(closes, fast), ema(closes, slow))]
    sig = ema(line, signal)
    return [a - b for a, b in zip(line, sig)]


def atr(bars, n=14):
    out, v, prev = [], None, None
    for b in bars:
        tr = b.h - b.l if prev is None else max(b.h - b.l, abs(b.h - prev), abs(b.l - prev))
        v = tr if v is None else (v * (n - 1) + tr) / n
        out.append(v)
        prev = b.c
    return out


def supertrend(bars, n=10, mult=3.0):
    """+1 in an uptrend, -1 in a downtrend (the classic ATR band flip)."""
    a = atr(bars, n)
    out, up_band, dn_band, trend = [], None, None, 1
    for i, b in enumerate(bars):
        mid = (b.h + b.l) / 2
        up, dn = mid - mult * a[i], mid + mult * a[i]
        if i:
            pc = bars[i - 1].c
            up = max(up, up_band) if pc > up_band else up
            dn = min(dn, dn_band) if pc < dn_band else dn
            if trend == 1 and b.c < up_band:
                trend = -1
            elif trend == -1 and b.c > dn_band:
                trend = 1
        up_band, dn_band = up, dn
        out.append(trend)
    return out


def stdev(xs, n):
    out = []
    for i in range(len(xs)):
        w = xs[max(0, i - n + 1):i + 1]
        m = sum(w) / len(w)
        out.append((sum((x - m) ** 2 for x in w) / len(w)) ** 0.5)
    return out


def bollinger(closes, n=20, k=2.0):
    mid, sd = sma(closes, n), stdev(closes, n)
    return mid, [m + k * s for m, s in zip(mid, sd)], [m - k * s for m, s in zip(mid, sd)]


def stochastic(bars, n=14, d=3):
    ks = []
    for i in range(len(bars)):
        w = bars[max(0, i - n + 1):i + 1]
        hh, ll = max(b.h for b in w), min(b.l for b in w)
        ks.append(50.0 if hh == ll else 100.0 * (bars[i].c - ll) / (hh - ll))
    return ks, sma(ks, d)


def adx(bars, n=14):
    """(ADX, +DI, -DI), Wilder smoothing."""
    adx_out, pdi_out, mdi_out = [], [], []
    tr_s = pdm_s = mdm_s = dx_s = None
    for i, b in enumerate(bars):
        if i == 0:
            adx_out.append(0.0), pdi_out.append(0.0), mdi_out.append(0.0)
            continue
        p = bars[i - 1]
        up, dn = b.h - p.h, p.l - b.l
        pdm = up if up > dn and up > 0 else 0.0
        mdm = dn if dn > up and dn > 0 else 0.0
        tr = max(b.h - b.l, abs(b.h - p.c), abs(b.l - p.c))
        if tr_s is None:
            tr_s, pdm_s, mdm_s = tr, pdm, mdm
        else:
            tr_s, pdm_s, mdm_s = tr_s + (tr - tr_s) / n, pdm_s + (pdm - pdm_s) / n, mdm_s + (mdm - mdm_s) / n
        pdi = 100.0 * pdm_s / tr_s if tr_s else 0.0
        mdi = 100.0 * mdm_s / tr_s if tr_s else 0.0
        dx = 100.0 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0
        dx_s = dx if dx_s is None else dx_s + (dx - dx_s) / n
        adx_out.append(dx_s), pdi_out.append(pdi), mdi_out.append(mdi)
    return adx_out, pdi_out, mdi_out


def cci(bars, n=20):
    tp = [(b.h + b.l + b.c) / 3 for b in bars]
    out = []
    for i in range(len(tp)):
        w = tp[max(0, i - n + 1):i + 1]
        m = sum(w) / len(w)
        md = sum(abs(x - m) for x in w) / len(w)
        out.append(0.0 if md == 0 else (tp[i] - m) / (0.015 * md))
    return out


def williams_r(bars, n=14):
    out = []
    for i in range(len(bars)):
        w = bars[max(0, i - n + 1):i + 1]
        hh, ll = max(b.h for b in w), min(b.l for b in w)
        out.append(-50.0 if hh == ll else -100.0 * (hh - bars[i].c) / (hh - ll))
    return out


def donchian_prev(bars, n=20):
    """The highest high and lowest low of the n bars BEFORE each bar (None until there are n)."""
    up, lo = [], []
    for i in range(len(bars)):
        if i < n:
            up.append(None), lo.append(None)
            continue
        w = bars[i - n:i]
        up.append(max(b.h for b in w)), lo.append(min(b.l for b in w))
    return up, lo


def roc(closes, n=10):
    return [0.0 if i < n else 100.0 * (c / closes[i - n] - 1) for i, c in enumerate(closes)]


def heikin_ashi(bars):
    """+1 after two green Heikin-Ashi candles, -1 after two red, else 0."""
    out, ho, hc, prev = [], None, None, 0
    for b in bars:
        c = (b.o + b.h + b.l + b.c) / 4
        o = (b.o + b.c) / 2 if ho is None else (ho + hc) / 2
        col = 1 if c > o else -1 if c < o else 0
        out.append(col if col == prev and col else 0)
        ho, hc, prev = o, c, col
    return out


def psar(bars, step=0.02, top=0.2):
    """Parabolic SAR trend: +1 while the SAR sits under price, -1 above."""
    if not bars:
        return []
    out, trend, sar, ep, af = [1], 1, bars[0].l, bars[0].h, step
    for i in range(1, len(bars)):
        b, p = bars[i], bars[i - 1]
        sar = sar + af * (ep - sar)
        if trend == 1:
            sar = min(sar, p.l, bars[i - 2].l if i > 1 else p.l)
            if b.l < sar:
                trend, sar, ep, af = -1, ep, b.l, step
            elif b.h > ep:
                ep, af = b.h, min(top, af + step)
        else:
            sar = max(sar, p.h, bars[i - 2].h if i > 1 else p.h)
            if b.h > sar:
                trend, sar, ep, af = 1, ep, b.h, step
            elif b.l < ep:
                ep, af = b.l, min(top, af + step)
        out.append(trend)
    return out


def session_twap(bars):
    """The day's running average of typical price ((h + l + c) / 3), reset each day."""
    out, day, s, n = [], None, 0.0, 0
    for b in bars:
        if b.t.date() != day:
            day, s, n = b.t.date(), 0.0, 0
        s += (b.h + b.l + b.c) / 3
        n += 1
        out.append(s / n)
    return out
