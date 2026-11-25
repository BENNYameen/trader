#!/usr/bin/env python3
"""Local dashboard for the Day Trader skill pack.

Standard library only. Binds to 127.0.0.1 (this computer only).
Runs the READ-ONLY tools and shows their output. It cannot place orders:
trader-broker, trader-risk and every --write flag are not exposed.

    python dashboard/server.py [--port 8765] [--workdir DIR]

--workdir is where the trader/ folder lives (default: current directory).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
TICKER = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
HHMM = re.compile(r"^\d{1,2}:\d{2}$")
INT = re.compile(r"^\d{1,3}$")
SETUPS = {"orb", "flag", "bounce"}
MEMBER = re.compile(r"^[A-Za-z]{2,30}$")

WORKDIR = Path.cwd()


def tool(script, *args):
    return [sys.executable, str(ROOT / script), *args]


def build(name, q):
    """Return an argv for a whitelisted tool, or raise ValueError."""
    g = lambda k, d="": (q.get(k, [d])[0] or d).strip()
    if name == "universe":
        return tool("trader-scanner/scan.py", "universe")
    if name == "daily":
        return tool("trader-scanner/scan.py", "daily")
    if name == "orb":
        at = g("at", "10:15")
        if not HHMM.match(at):
            raise ValueError("bad time, use HH:MM")
        return tool("trader-scanner/scan.py", "orb", "--at", at)
    if name == "news":
        t, h = g("ticker").upper(), g("hours", "12")
        if not TICKER.match(t) or not INT.match(h):
            raise ValueError("bad ticker or hours")
        return tool("trader-news/news.py", "--tickers", t, "--hours", h)
    if name == "entry":
        t, s = g("ticker").upper(), g("setup", "orb")
        if not TICKER.match(t) or s not in SETUPS:
            raise ValueError("bad ticker or setup")
        return tool("trader-entry/entry.py", "check", t, "--setup", s)
    if name == "analyst":
        t = g("ticker").upper()
        if not TICKER.match(t):
            raise ValueError("bad ticker")
        return tool("trader-analyst/facts.py", t)
    if name == "score":
        return tool("trader-broker/practice.py", "score")
    if name == "pelosi":
        m = g("member", "pelosi")
        if not MEMBER.match(m):
            raise ValueError("bad member")
        return tool("trader-pelosi/ptr.py", "index", "--member", m)
    raise ValueError("unknown tool")


def run(argv, market="auto"):
    """market: "us" or "in" pins TRADER_MARKET for this run; "auto" lets the tool read
    "market" from trader/config.json in the workdir (us when there is none)."""
    env = dict(os.environ)
    env.pop("TRADER_MARKET", None)
    if market in ("us", "in"):
        env["TRADER_MARKET"] = market
    env["PYTHONIOENCODING"] = "utf-8"   # headlines can carry any character
    try:
        p = subprocess.run(argv, cwd=WORKDIR, capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace", timeout=280)
        return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr).strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "timed out after 280 s"}


def configured_market():
    try:
        with open(WORKDIR / "trader" / "config.json", encoding="utf-8") as fh:
            m = str(json.load(fh).get("market") or "us").lower()
    except (OSError, ValueError, AttributeError):
        m = "us"
    return m if m in ("us", "in") else "us"


def state():
    out = {}
    base = WORKDIR / "trader"
    for rel in ("config.json", "plan.json", "orders.json", "portfolio.json",
                "state/risk.json", "state/broker.json", "alerts.json"):
        f = base / rel
        if f.is_file():
            try:
                out[rel] = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                out[rel] = f"unreadable: {e}"
    return out


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Day Trader Dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#14181f;--mut:#5b6573;--bd:#dfe3e8;--ac:#0b6bcb;--ok:#14803c;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--card:#171c23;--fg:#e8ecf1;--mut:#97a1ae;--bd:#2a313b;--ac:#5aa9ff;--ok:#4cc27a;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{padding:16px;border-bottom:1px solid var(--bd);display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
h1{font-size:18px;margin:0}small{color:var(--mut)}
main{max-width:1100px;margin:0 auto;padding:16px;display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(320px,1fr))}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px}
.card h2{font-size:15px;margin:0 0 4px}.card p{margin:0 0 10px;color:var(--mut);font-size:13px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
input,select{background:var(--bg);color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:6px 8px;font:inherit;width:90px}
button{background:var(--ac);color:#fff;border:0;border-radius:6px;padding:7px 12px;font:inherit;cursor:pointer}
button:disabled{opacity:.5;cursor:wait}
pre{margin:0;padding:10px;background:var(--bg);border:1px solid var(--bd);border-radius:6px;max-height:340px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,Consolas,monospace}
pre.err{color:var(--bad)}.wide{grid-column:1/-1}
</style></head><body>
<header><h1>Day Trader Dashboard</h1><small>local only &middot; read-only &middot; no orders can be placed here</small>
<label style="margin-left:auto">Market <select id="mkt" style="width:auto"><option value="auto">auto</option><option value="us">US (NYSE, ET, $)</option><option value="in">India (NSE, IST, Rs)</option></select></label></header>
<main>
<section class="card"><h2>Daily scan</h2><p>Whole universe, pre-market setups. Takes about 1 minute.</p>
<div class="row"><button data-t="daily">Run</button><button data-t="universe">Refresh universe</button></div><pre id="o-daily">idle</pre></section>
<section class="card"><h2>Opening-range breakouts</h2><p>Market hours only.</p>
<div class="row"><input id="orb-at" value="10:15" aria-label="time"><button data-t="orb" data-f="orb-at:at">Run</button></div><pre id="o-orb">idle</pre></section>
<section class="card"><h2>News</h2><p>Headlines and today's move. US: Yahoo + SEC 8-Ks (need SEC_USER_AGENT). India: Google News.</p>
<div class="row"><input id="news-t" value="TSLA" aria-label="ticker"><input id="news-h" value="12" aria-label="hours" style="width:60px"><button data-t="news" data-f="news-t:ticker,news-h:hours">Run</button></div><pre id="o-news">idle</pre></section>
<section class="card"><h2>Entry check</h2><p>Waiting, triggered or expired.</p>
<div class="row"><input id="ent-t" value="TSLA" aria-label="ticker"><select id="ent-s"><option>orb</option><option>flag</option><option>bounce</option></select><button data-t="entry" data-f="ent-t:ticker,ent-s:setup">Check</button></div><pre id="o-entry">idle</pre></section>
<section class="card"><h2>Earnings analyst</h2><p>Quarters, growth, EPS. US only (SEC EDGAR); needs SEC_USER_AGENT.</p>
<div class="row"><input id="an-t" value="TSLA" aria-label="ticker"><button data-t="analyst" data-f="an-t:ticker">Run</button></div><pre id="o-analyst">idle</pre></section>
<section class="card"><h2>Congress trades</h2><p>House Clerk PTR index this year. US only.</p>
<div class="row"><input id="pel-m" value="pelosi" aria-label="member"><button data-t="pelosi" data-f="pel-m:member">Run</button></div><pre id="o-pelosi">idle</pre></section>
<section class="card wide"><h2>Practice scoreboard</h2><p>Your paper month: trades, wins, P&amp;L after estimated charges, balance.</p>
<div class="row"><button data-t="score">Refresh</button></div><pre id="o-score">idle</pre></section>
<section class="card wide"><h2>Your trader/ files</h2><p>Plan, orders, risk verdicts, broker log, as written by the skills.</p>
<div class="row"><button id="st">Reload</button></div><pre id="o-state">idle</pre></section>
</main>
<script>
async function go(btn){
  const t=btn.dataset.t, out=document.getElementById('o-'+t), p=new URLSearchParams();
  (btn.dataset.f||'').split(',').filter(Boolean).forEach(x=>{const [id,k]=x.split(':');p.set(k,document.getElementById(id).value)});
  p.set('market', document.getElementById('mkt').value);
  btn.disabled=true;out.className='';out.textContent='running...';
  try{const r=await fetch('/api/run/'+t+'?'+p);const j=await r.json();
    out.className=j.ok?'':'err';out.textContent=j.output||j.error||'(no output)';}
  catch(e){out.className='err';out.textContent=String(e)}
  btn.disabled=false;
}
document.querySelectorAll('button[data-t]').forEach(b=>b.onclick=()=>go(b));
async function st(){const o=document.getElementById('o-state');
  const j=await (await fetch('/api/state')).json();
  o.textContent=Object.keys(j).length?JSON.stringify(j,null,2):'No trader/ files in the working folder yet.';}
document.getElementById('st').onclick=st;st();
let configured='us';
const mkt=document.getElementById('mkt');
function effective(){return mkt.value==='auto'?configured:mkt.value;}
function tickers(){  // swap the example ticker when the market changes
  const want=effective()==='in'?'RELIANCE':'TSLA', other=want==='TSLA'?'RELIANCE':'TSLA';
  ['news-t','ent-t','an-t'].forEach(id=>{const el=document.getElementById(id);if(el.value===other)el.value=want;});
  document.getElementById('orb-at').value=document.getElementById('orb-at').value||'10:15';
}
mkt.onchange=tickers;
fetch('/api/market').then(r=>r.json()).then(j=>{configured=j.configured;
  mkt.options[0].text='auto: '+(configured==='in'?'India':'US')+' (trader/config.json)';tickers();});
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        # block DNS-rebinding: only answer to localhost host names
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._json(403, {"ok": False, "error": "forbidden host"})
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._json(200, state())
        if u.path == "/api/market":
            return self._json(200, {"configured": configured_market()})
        if u.path.startswith("/api/run/"):
            q = parse_qs(u.query)
            market = (q.get("market", ["auto"])[0] or "auto").lower()
            if market not in ("auto", "us", "in"):
                return self._json(400, {"ok": False, "error": "market is auto, us or in"})
            try:
                argv = build(u.path[len("/api/run/"):], q)
            except ValueError as e:
                return self._json(400, {"ok": False, "error": str(e)})
            return self._json(200, run(argv, market))
        self._json(404, {"ok": False, "error": "not found"})

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % a))


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already taken, and
    # requests then go to whichever process Windows picks. Without it a second copy fails loudly.
    allow_reuse_address = os.name != "nt"


def main():
    global WORKDIR
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--workdir", default=".")
    a = ap.parse_args()
    WORKDIR = Path(a.workdir).resolve()
    WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        srv = Server(("127.0.0.1", a.port), H)
    except OSError as e:
        raise SystemExit("port %d is taken (%s): is the dashboard already running? Stop it, or use --port"
                         % (a.port, e))
    print(f"Dashboard: http://127.0.0.1:{a.port}  (workdir {WORKDIR})  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
