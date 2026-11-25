---
name: india-zerodha-setup
description: User trades Indian markets through Zerodha; day-trader-skill runs in India mode; Kite MCP is read-only except GTT
metadata:
  node_type: memory
  type: project
  originSessionId: 14016a46-58dd-4c5e-b397-b98990a3d0c9
  modified: 2026-11-19T10:03:18.856Z
---

The user trades the Indian market with Zerodha and asked for a US/India toggle rather than an India-only fork. India mode was built on 2026-11-19: `"market": "in"` in the gitignored `trader/config.json` (or `TRADER_MARKET=in`), with the US as default. The stock budget was set to Rs 15,000 on 2026-11-19, after Rs 2,000 and then Rs 5,000 earlier the same day. The current limits are in [[practice-month]].

**Why:** Zerodha's free hosted Kite MCP (`https://mcp.kite.trade/mcp`, in the project `.mcp.json`; deny/ask/allow rules in `.claude/settings.local.json`) is read-only except GTT orders, and Zerodha has no paper account. So the broker step renders manual Kite-app steps, and `"paper": true` means practice. Placing orders by API would need a paid Kite Connect app plus a static IP (required since 2026-04-01).

**How to apply:** never claim Claude can place regular Zerodha orders. NSE's site blocks scripts, so the user saves `EQUITY_L.csv` from a browser if they want the full universe. Do not add header spoofing to get around that.
