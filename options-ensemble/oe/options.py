"""Index option pricing (Black-Scholes, India VIX as the volatility), weekly expiry calendars,
Zerodha's option charges and the strike choice, for NIFTY (NSE) and SENSEX (BSE).

Prices here are estimates: real weekly premiums differ from Black-Scholes with VIX (smile,
spreads, demand). Good enough to compare methods with each other; not a quote."""

import datetime
import math

RATE = 0.06
# weekday numbers: Monday 0 ... Friday 4. "until" is the first day the next rule applies.
INDICES = {
    "NIFTY": {"yahoo": "^NSEI", "lot": 65, "step": 50, "exchange": "NSE", "txn": 0.0003553,
              # weekly expiry Thursday up to 2025-08-28, Tuesday from 2025-09-02
              "weekdays": [(datetime.date(2025, 8, 29), 3), (None, 1)]},
    "SENSEX": {"yahoo": "^BSESN", "lot": 20, "step": 100, "exchange": "BSE", "txn": 0.000325,
               # weekly expiry Friday after the 2023 relaunch, Tuesday through most of 2025,
               # Thursday since September 2025 (SEBI: NSE Tuesday, BSE Thursday)
               "weekdays": [(datetime.date(2025, 1, 1), 4), (datetime.date(2025, 9, 1), 1), (None, 3)],
               "lot_from": [(datetime.date(2027, 1, 1), 25)]},   # BSE notice 20260930-58
}
LOT = INDICES["NIFTY"]["lot"]          # NIFTY lot from January 2026 (it was 75, and 25 before Nov 2024)
STEP = INDICES["NIFTY"]["step"]
SWITCH = datetime.date(2025, 8, 29)    # NIFTY: Thursday up to 2025-08-28, Tuesday from 2025-09-02
NSE_HOLIDAYS_2026 = {                  # BSE closes on the same days for equity and derivatives
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10",
    "2026-11-24", "2026-12-25"}


def _n(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def price(spot, strike, years, vol, kind):
    """Black-Scholes premium of a call ("CE") or put ("PE")."""
    intrinsic = max(0.0, spot - strike) if kind == "CE" else max(0.0, strike - spot)
    if years <= 0 or vol <= 0:
        return intrinsic
    sq = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (RATE + vol * vol / 2) * years) / sq
    d2 = d1 - sq
    disc = math.exp(-RATE * years)
    if kind == "CE":
        return spot * _n(d1) - strike * disc * _n(d2)
    return strike * disc * _n(-d2) - spot * _n(-d1)


def lot_for(index, expiry):
    lot = INDICES[index]["lot"]
    for start, size in INDICES[index].get("lot_from", []):
        if expiry >= start:
            lot = size
    return lot


def expiry_weekday(index, d):
    for until, wd in INDICES[index]["weekdays"]:
        if until is None or d < until:
            return wd
    return INDICES[index]["weekdays"][-1][1]


def is_trading_day(d, known_days, last_known):
    if d <= last_known:
        return d in known_days
    return d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS_2026


def next_expiry(d, known_days, last_known, index="NIFTY"):
    """The nearest weekly expiry AFTER day d (never today: no expiry-day trades). A holiday
    moves an expiry to the trading day before."""
    cand = d + datetime.timedelta(days=1)
    for _ in range(30):
        if cand.weekday() == expiry_weekday(index, cand):
            e = cand
            while not is_trading_day(e, known_days, last_known):
                e -= datetime.timedelta(days=1)
            if e > d:
                return e
        cand += datetime.timedelta(days=1)
    raise ValueError("no expiry found after %s" % d)


def years_to(t, expiry):
    return max(0.0, (datetime.datetime.combine(expiry, datetime.time(15, 30)) - t).total_seconds()) / (365 * 86400)


def charges(buy_value, sell_value, index="NIFTY"):
    """Zerodha option charges for one buy and one sell (zerodha.com/charges, read 2026-11-19):
    Rs 20 an order; STT 0.15% of the sell premium; exchange 0.03553% of premium on NSE,
    0.0325% on BSE; SEBI Rs 10 a crore; GST 18% on brokerage, exchange and SEBI; stamp 0.003%
    of the buy."""
    brokerage = 40.0
    stt = 0.0015 * sell_value
    txn = INDICES[index]["txn"] * (buy_value + sell_value)
    sebi = 0.000001 * (buy_value + sell_value)
    gst = 0.18 * (brokerage + txn + sebi)
    stamp = 0.00003 * buy_value
    return round(brokerage + stt + txn + sebi + gst + stamp, 2)


def choose_strike(spot, years, vol, kind, max_loss, stop_pct, cash, slip, index="NIFTY", lot=None):
    """At the money if it fits, else step out of the money (cheaper) until the loss at the
    premium stop fits max_loss and one lot fits the cash. None when nothing fits."""
    step = INDICES[index]["step"]
    lot = lot or INDICES[index]["lot"]
    atm = int(round(spot / step) * step)
    for k in range(9):
        strike = atm + k * step if kind == "CE" else atm - k * step
        prem = price(spot, strike, years, vol, kind) + slip
        if prem < 1.0:
            return None
        if prem * lot * stop_pct <= max_loss and prem * lot <= cash:
            return strike, prem
    return None
