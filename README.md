# DESK v1 — PAPER-ONLY Solana memecoin desk (Hrundel-style rules)

Paper only. No wallets, keys, seeds, logins, or real orders exist anywhere in this code.
Start balance: $1,000 paper USD. Default mode: goal, finish line $2,000 paper (2x).

## Run (v2)
    python3 desk.py setup "trade overnight $500 degen"     # Chief of Staff: sentence -> setup card -> background session (ends 07:00)
    python3 desk.py setup "two fifty beat my paycheck before I clock out" --goal 1412.06   # 9-5 session, ends 17:00
    python3 desk.py setup "..." --dry                      # card only, no session
    python3 desk.py start --minutes 20 --mode goal --goal 2000
    python3 desk.py stop [--sell-all]                      # "Stop & sell all"
    python3 desk.py pick <mint> <usd>                      # sell-for-me: you pick, Exit sells
    python3 desk.py messages                               # morning message, recap, last sell alerts
    python3 desk.py push topic|on|off|test                 # ntfy.sh alerts (OFF by default; outbox.jsonl keeps every message)
    python3 desk.py scan | status
    python3 build_page_data.py                             # ledger -> page_data_min.json / page_data_lines.txt for the Page
    python3 test_paper.py                                  # offline checks of every mode's exits
    compare/harness/render.sh <canvas.tsx> out.png         # local render of the Page for screenshot comparison
Sessions always have an end time (max 12 h). Modes and rules: config.MODE_RULES. Audit: GAPS.md.

## Bots (v4): JEV + 7 seats, each its own process, talking on a bus
`desk.py setup/start` → JEV (the chief, `bots/jev.py`) starts SCAN, VET, SOCIAL, SIZE, FILLS, RISK, PIGGY as separate
processes (`python -m bots.run NAME SID …`, logs `session-SID-NAME.log`). They talk only through `bots/bus.py`
(sqlite `bus.db`: from/to/type/task/text/payload/ts + heartbeats). FILLS is the only writer of the book.
JEV asks typed questions (`bots/questions.py`, his thresholds.py numbers) answered by LOCAL RULES. There's no TypeSafe key,
so the numbers are not calibrated probabilities. At session end JEV → FILLS flatten → session_end → shutdown → every process exits.
    python3 desk.py bus 60          # last messages + every seat's heartbeat
Spec with sources (verified vs inferred), bus design, plugin options, limits: BOTS_SPEC.md.

## Cloud sessions (v5): GitHub Actions, so the box can sleep
    python3 cloud.py start --minutes 360 --mode goal   # book -> branch `book` of kubebehog/Jev-desk, run there (legs of <=345 min chain)
    python3 cloud.py status | pull                     # pull = take the cloud book back + rebuild page data
Code on `main`, data on `book`, commits every 10 min, flatten + final commit even on cancel. Details: CLOUD.md.

## Files
config.py (all thresholds) · sources.py (DexScreener, RugCheck, Solana public RPC, PumpPortal WS, pump.fun attempt)
scanner.py (radar) · analyst.py (hard filters, PASS/FAIL/UNKNOWN; UNKNOWN = FAIL) · signals.py (momentum, pre-trending, CTO watch)
executor.py (paper fills) · risk.py (stop/ladder/trail/goal) · store.py (append-only ledger.jsonl + state.json)

## Rules
Hard checks: liq >= $20K · mint authority revoked (Solana RPC) · dev wallet < 5% (RugCheck creator + live RPC balance)
· top-10 holders <= 30% excl. pools/lockers (RugCheck) · LP burned/locked >= 90% · not bundled (proxy: RugCheck insider graph = 0).
Max 2 open · size 60% of free cash (goal/fix-bags/sell-for-me), 40% (pre-trending/cto-watch), 100% one-coin
· stop -18% (one-coin -5%) · ladder: +15% sell 30%, +30% sell 30%, last 40% on a 12% trail (15% pre-trending/cto, 8% one-coin) · goal stop sells all and halts.

## Cost model (assumption)
Buy fill = quote x (1 + slip), sell fill = quote x (1 - slip), slip = 0.5% + ticket / (liquidity_usd / 2), capped 15%.
Fee 1.0% of notional per side. Positions are marked at net liquidation value (same slip+fee).
Exits are checked every 30s on DexScreener quotes, so a stop can fill past -18% on a gap.

