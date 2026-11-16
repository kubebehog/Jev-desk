"""Offline check of fills and every mode's exits on a temp ledger/outbox (never touches ledger.jsonl)."""
import tempfile, os
import store, notify
D = tempfile.mkdtemp(); store.LEDGER = os.path.join(D, "l.jsonl"); store.STATE = os.path.join(D, "s.json"); notify.OUTBOX = os.path.join(D, "o.jsonl")
import executor, risk, messages, chief, config

row = {"mint": "M", "symbol": "T", "price": 1.0, "liq": 100000, "mcap": 50000}
q = lambda px: {"M": {"price": px, "liq": 100000, "vol_h1": 1e5, "mcap": 50000 * px}}


def fresh(mode, usd=600, goal=None):
    s = store.default_state(); s["mode"] = mode; s["vault"] = 0
    s["session"] = {"start_equity": 1000.0, "goal_usd": goal}
    executor.paper_buy(s, row, usd, "t", mode); return s


s = fresh("goal"); risk.manage(s, q(1.30)); risk.manage(s, q(1.10))       # 15.4% off the top -> Banker trail 12%
assert "M" not in s["positions"]; print("goal trail ok", round(s["cash"], 2))
s = fresh("goal"); risk.manage(s, q(0.80)); assert "M" not in s["positions"]; print("goal stop -18 ok", round(s["cash"], 2))
s = fresh("degen", 240); risk.manage(s, q(1.03)); assert s["positions"]["M"]["stop_at_entry"]
risk.manage(s, q(1.00)); assert "M" not in s["positions"]; print("degen stop moved to entry ok")
s = fresh("degen", 240); risk.manage(s, q(0.93)); assert "M" not in s["positions"]; print("degen -6 ok")
s = fresh("sell-for-me", 160); risk.manage(s, q(2.10)); p = s["positions"]["M"]; assert abs(p["qty"] / p["qty0"] - 0.75) < 1e-9
risk.manage(s, q(8.0)); risk.manage(s, q(6.7)); assert "M" not in s["positions"]; print("sell-for-me 25% at x2 + 15% trail ok", round(s["cash"], 2))
s = fresh("goal", 600, goal=1100); eq = risk.equity(s, q(1.3)); assert risk.goal_check(s, q(1.3), eq) and s["halted"]; print("goal stop ok")
s = fresh("compound", 600); risk.manage(s, q(5)); risk.manage(s, q(4)); s["session"]["start_equity"] = 500; risk.piggy(s); assert s["vault"] == 500; print("piggy lock ok", s["vault"])
s = fresh("fix-bags", 300); qq = q(1.0); qq["M"]["liq"] = 5000; risk.manage(s, qq); assert "M" not in s["positions"]; print("dead bag ok")
L = store.read_ledger()
print(messages.sell_alert([x for x in L if x["kind"] == "trade" and x["side"] == "SELL"][0]))
print(open(notify.OUTBOX).readline()[:200])
print(chief.parse("Turn twenty into rent twenty four hundred and stop")["goal_usd"])

# ---- sessions never leave positions open (end time, stop, goal, crash) — JEV + all seats, stepped inline ----
notify.cfg = lambda: {"topic": "test", "enabled": False}   # tests never post anywhere
import time as _time, desk, sources, market, scanner, analyst
from bots import bus
config.BOTS_INLINE = True
desk.STOPFLAG = os.path.join(D, "STOP")
PX = {"px": 1.0}
fakeq = lambda mints: {m: {"mint": m, "symbol": "T", "price": PX["px"], "liq": 100000, "vol_h1": 1e5, "mcap": 5e4, "ts": _time.time()} for m in mints}
desk.quotes_for = market.quotes = fakeq
scanner.scan = lambda pp=None: ([], {})
sources.PumpPortal = lambda: None


def session_state(minutes, mode="goal", hold=True):
    s = store.default_state(); s["vault"] = 0; s["nights"] = 0
    if hold: executor.paper_buy(s, row, 300, "t", mode)
    store.save_state(s)
    sid = desk.new_session(s, "custom", _time.time() + minutes * 60, mode, None)
    return sid


def boom(_):
    raise KeyboardInterrupt()


hooks = {"end time": lambda _: real_sleep(0.6),              # session end time passes
         "stop": lambda _: open(desk.STOPFLAG, "w").write("stop"),  # `desk.py stop` arrives mid-session
         "crash": boom}                                       # process killed / exception escapes the loop
real_sleep = _time.sleep
for label, hook in hooks.items():
    sid = session_state(0.02 if label == "end time" else 5)
    desk.time.sleep = hook
    try:
        desk.run(sid, tick=0)
    finally:
        desk.time.sleep = real_sleep
    if os.path.exists(desk.STOPFLAG): os.remove(desk.STOPFLAG)
    st = store.load_state()
    assert st["positions"] == {}, (label, st["positions"])
    last = [x for x in store.read_ledger() if x["kind"] == "session_end"][-1]
    assert bus.find(sid, frm="FILLS", type="flat") or label == "crash", label
    assert {m["frm"] for m in bus.find(sid, type="shutdown")} == {"JEV"}
    print(f"session end via {last['why']}: 0 positions left ok")
# goal hit: PIGGY tells JEV, JEV turns the desk off, FILLS flattens
sid = session_state(5); st = store.load_state(); st["session"]["goal_usd"] = 100; store.save_state(st)
desk.run(sid, tick=0); assert store.load_state()["positions"] == {}
assert bus.find(sid, frm="PIGGY", type="goal_hit") and bus.find(sid, frm="JEV", type="decision"); print("session end via goal (PIGGY -> JEV -> FILLS): 0 positions left ok")

from bots import questions as Q
Q.jup_quote = lambda mint, amount: ({"outAmount": "123", "routePlan": [{}], "priceImpactPct": "0.004"}, None)   # tests never call Jupiter
# ---- the full chain on the bus: SCAN -> VET -> SOCIAL -> JEV -> SIZE -> FILLS, then RISK -> FILLS, JEV cooldown veto ----
from bots.jev import Jev, SEATS
C = {"mint": "C1", "symbol": "PIGC", "name": "Pig Coin", "dex": "pumpswap", "pair": None, "url": "u", "price": 1.0, "liq": 200000, "mcap": 9e5,
     "vol_m5": 5000, "vol_h1": 60000, "buys_m5": 40, "sells_m5": 10, "buys_h1": 300, "sells_h1": 100, "chg_m5": 3, "chg_h1": 12, "age_h": 30,
     "socials": True, "feeds": ["ds_profiles"]}
scanner.scan = lambda pp=None: ([dict(C)], {"ds_profiles": 1})
analyst.vet = lambda r, pp=None: {"passed": True, "holders": 900, "dev_pct": 0.0, "checks": [{"check": "not bundled (proxy)", "verdict": "PASS", "value": 0},
    {"check": "mint authority revoked", "verdict": "PASS", "value": "none"}, {"check": "top wallet <= 6%", "verdict": "PASS", "value": 2.0},
    {"check": "top-10 holders <= 30%", "verdict": "PASS", "value": 20.0}]}
sources.ds_pairs = lambda mints: {m: {"info": {"socials": [{"type": "twitter", "url": "https://x.com/pigcoin"}]}, "boosts": {"active": 2}} for m in mints}
sources.get = lambda url, timeout=15: {"orders": [{"type": "tokenProfile", "status": "approved"}]}
desk.quotes_for = market.quotes = lambda mints: {m: {"mint": m, "symbol": "PIGC", "price": PX["px"], "liq": 200000, "vol_h1": 6e4, "mcap": 9e5, "ts": _time.time()} for m in mints}
PX["px"] = 1.0
sid = session_state(5, hold=False)
seats = [c(sid, bus.last_id()) for c in SEATS]; j = Jev(sid, seats[0].cursor)
step = lambda n=1: [b.step() for _ in range(n) for b in seats + [j]]
step(3)
for who, typ in [("SCAN", "candidates"), ("VET", "vetted"), ("SOCIAL", "social"), ("JEV", "pick"), ("SIZE", "order"), ("FILLS", "filled")]:
    m = bus.find(sid, frm=who, type=typ); assert m, (who, typ); assert who == "SCAN" or m[-1]["task"] in (None, "C1"), (who, m[-1]["task"])
assert "C1" in store.load_state()["positions"]; print("chain SCAN->VET->SOCIAL->JEV->SIZE->FILLS ok:", bus.find(sid, frm="SIZE", type="order")[-1]["text"])
assert bus.find(sid, frm="SOCIAL", type="social")[-1]["payload"]["rows"][0]["social"]["x_handle"] == "pigcoin"
pos = store.load_state()["positions"]["C1"]; assert pos["cost_usd"] <= 200.0 + 1e-9, pos["cost_usd"]    # entry guards via SIZE (20% cap)
PX["px"] = 0.70; seats[5]._t = 0; step(2)                                                       # -30% -> RISK stop -18% -> FILLS sells
assert "C1" not in store.load_state()["positions"] and bus.find(sid, frm="RISK", type="order"); print("RISK -> FILLS stop ok")
assert bus.find(sid, frm="JEV", type="veto"), "loss cooldown veto"; print("JEV loss cooldown veto ok:", bus.find(sid, frm="JEV", type="veto")[-1]["text"])
PX["px"] = 1.0; seats[0]._t = 0; step(3)
assert "C1" not in store.load_state()["positions"]; print("JEV vetoes re-entry during cooldown ok")
# JEV's question sets (his thresholds.py lines, local rules): missing = fail, concentration kill, no X handle = 0.60x, pick lines
from bots import questions as Q
good = {**C, "passed": True, "dev_pct": 0.1, "vet": analyst.vet(C)["checks"], "social": {"x_handle": "pigcoin"}}
A = {**Q.market(good, 100), **Q.solana(good), **Q.social(good), **Q.about_me(good)}
assert Q.soft_kill({**A, **Q.about_me({**good, "chg_h1": 60})}) == "looks_like_my_losses"
assert Q.soft_kill(A) is None, A
assert Q.soft_kill({**A, **Q.solana({**good, "dev_pct": None})}) == "dev_still_loaded"                       # missing = fail
whale = {**good, "vet": [dict(c, value=8.0) if c["check"].startswith("top wallet") else c for c in good["vet"]]}
assert Q.soft_kill({**A, **Q.solana(whale)}) == "concentration_is_exit_risk"
assert Q.soft_kill({**A, **Q.market({**good, "liq": 3000}, 100)}) == "liquidity_fits_ticket"
assert Q.soft_kill({**A, **Q.market({**good, "sells_m5": 90, "sells_h1": 900}, 100)}) == "shape"
assert Q.social({**good, "social": {"x_handle": None}}) == {}                                                 # → NO_SOCIAL_CUT
r1, r2 = dict(good, mint="A", answers=A), dict(good, mint="B", answers={**A, **Q.market({**good, "chg_h1": 90}, 100)})
pk = Q.pick([r1, r2]); assert pk["best"]["choice"] == "A" and pk["worth_trading_at_all"]["noul"] >= Q.PICK_MIN_WORTH, pk
print("JEV question sets ok: missing=fail, concentration/liquidity/shape kills, no-X cut, pick prefers the unspent setup")
# RISK volume-decay rule (6h < 20% of the 24h average)
acts, _ = risk.decide({"mode": "goal", "entry_fill": 1.0, "peak": 1.0, "symbol": "X"}, {"price": 1.05, "liq": 1e5, "vol_h6": 100, "vol_h24": 4000}, {})
assert acts and acts[0][0] == 1.0 and "volume dying" in acts[0][1], acts; print("RISK volume-decay close ok:", acts[0][1])
# PIGGY compounder lock goes through FILLS (the only writer of the book)
st = store.load_state(); st["mode"] = "compound"; st["cash"] = 2500; st["session"]["start_equity"] = 1000; store.save_state(st)
seats[4].st = store.load_state(); seats[6]._t = 0; step(2)
assert store.load_state()["vault"] == 1000 and bus.find(sid, frm="FILLS", type="locked"); print("PIGGY -> FILLS vault lock ok")
# setup/start refuse orphans
s = store.default_state(); executor.paper_buy(s, row, 100, "t", "goal"); s["session"] = None; store.save_state(s)
try:
    desk.refuse_orphans(s); raise AssertionError("should refuse")
except SystemExit as e:
    print("refuse orphans ok:", str(e)[:60])
# entry guards (RESEARCH.md): size cap, ticket vs liquidity, slippage cap, min ticket, anti-chase, off switch
s = store.default_state(); s["cash"] = 1000.0
r = {"liq": 30_000, "chg_h1": 30}
usd, why = risk.ticket(s, r, 0.60); assert why is None and usd == 150.0, (usd, why)          # 0.5% of $30K liq beats 20% of cash
assert executor.slip_pct(usd, r["liq"]) <= config.MAX_ENTRY_SLIP_PCT
usd, why = risk.ticket(s, {"liq": 500_000}, 0.60); assert usd == 200.0, usd                     # 20% cash cap
usd, why = risk.ticket(s, {"liq": 1_500}, 0.60); assert usd == 0 and "under" in why, why       # thin pool -> skip
old = config.MAX_TICKET_PCT_OF_LIQ; config.MAX_TICKET_PCT_OF_LIQ = 5.0
usd, why = risk.ticket(s, {"liq": 20_000}, 0.60); assert usd == 0 and "slippage" in why, why    # 5% of liq -> >2% slip -> skip
config.MAX_TICKET_PCT_OF_LIQ = old
config.MAX_ENTRY_CHG_H1 = 100; usd, why = risk.ticket(s, {"liq": 90_000, "chg_h1": 204}, 0.6); assert usd == 0 and "anti-chase" in why
config.MAX_ENTRY_CHG_H1 = None
config.ENTRY_GUARDS = False; usd, why = risk.ticket(s, {"liq": 20_000}, 0.60); assert usd == 600.0 and why is None
config.ENTRY_GUARDS = True
print("entry guards ok")
# ---- honest coverage: wall-clock gaps (synthetic timestamps) ----
assert messages.gaps([0, 15, 30, 45]) == []
G = messages.gaps([0, 15, 30, 2265, 2280, 2295, 22100]); assert [g[2] for g in G] == [37.2, 330.1], G
from bots.jev import check_gap
from bots.risk_bot import Risk
gsid = session_state(5, hold=True); jg = Jev(gsid, bus.last_id()); rk = Risk(gsid, jg.cursor); rk._t = _time.time()
now = _time.time(); assert check_gap(jg, now - 30, now) == now and not [x for x in store.read_ledger() if x["kind"] == "gap"]   # 30 s: no gap
check_gap(jg, now - 37 * 60, now)
g = [x for x in store.read_ledger() if x["kind"] == "gap"][-1]
assert g["paper"] and g["sid"] == gsid and g["minutes"] == 37.0 and g["to_ts"] - g["from_ts"] > 2000, g
lg = [x for x in store.read_ledger() if x["kind"] == "log"][-1]["msg"]; assert "box was paused 37 min (no scanning, no stops watched)" in lg and "RISK re-checks now" in lg, lg
for m in bus.inbox("RISK", rk.cursor):
    rk.cursor = m["id"]; rk.on(m)
assert rk._t == 0, "RISK re-checks open positions right after a gap"
# coverage from equity timestamps: 60 min session, snapshots every 15 s with a 30 min hole
t0 = 1_000_000.0
E = lambda k: {"ts": t0 + k, "kind": "equity", "sid": "X", "equity": 1000.0, "open": 0}
CL = [{"ts": t0, "kind": "session_start", "sid": "X", "end_ts": t0 + 3600, "start_equity": 1000.0}] + \
     [E(k) for k in range(15, 1800, 15)] + [E(k) for k in range(3600, 3615, 15)] + \
     [{"ts": t0 + 3615, "kind": "session_end", "sid": "X"}]
cv = messages.coverage(CL, "X"); assert len(cv["gaps"]) == 1 and abs(cv["active_min"] - 30.0) < 0.1 and cv["sched_min"] == 60, cv
assert "Active 30 of 60 min (50%) · 1 gap" in messages.recap(CL, "X"), messages.recap(CL, "X")
print("gap detection ok:", lg, "·", messages.recap(CL, "X").splitlines()[-1])
# ---- sell-simulation gate decision (stubbed Jupiter quote dicts) ----
ok_q = {"outAmount": "5000", "routePlan": [{"swapInfo": {}}], "priceImpactPct": "0.0123"}
assert Q.sell_decision(ok_q)[0] == 1.0
assert Q.sell_decision({**ok_q, "priceImpactPct": "0.0535"})[0] == 0.0                              # > 5% impact
assert Q.sell_decision({**ok_q, "routePlan": []})[0] == 0.0                                         # no route
assert Q.sell_decision({k: v for k, v in ok_q.items() if k != "priceImpactPct"})[0] is None        # missing = fail
assert Q.sell_decision(None, "no route: TOKEN_NOT_TRADABLE")[0] == 0.0
v, _, why = Q.sell_decision(None, "jupiter down: ConnectionError"); assert v is None and why.startswith("jupiter down")
seen = {}
def stubq(mint, amount): seen["amount"] = amount; return ok_q, None
a = Q.sell_route({"mint": "C1", "price": 0.002, "decimals": 6}, 100.0, stubq)["sell_route_ok"]
assert seen["amount"] == 50_000 * 10**6 and a["noul"] == 1.0, (seen, a)                              # $100 / $0.002 = 50,000 tokens
assert Q.sell_route({"mint": "C1", "price": 0}, 100.0, stubq)["sell_route_ok"]["noul"] is None
assert Q.soft_kill({"sell_route_ok": {"noul": 0.0}}) == "sell_route_ok" and Q.soft_kill({"sell_route_ok": {"noul": None}}) == "sell_route_ok"
# wired into JEV's judge: asked only after everything else passed, a honeypot is killed by it
from bots.jev import judge
book = {"cash": 1000.0, "positions": {}, "mode": "goal"}
cand = {**good, "price": 1.0, "decimals": 6, "candles": None, "chg_h1": 5}
Q.jup_quote = lambda mint, amount: (None, "no route: NO_ROUTES_FOUND")
ok, A, sig, kill = judge(dict(cand), "goal", book)
assert kill == "sell_route_ok" and not ok and A["sell_route_ok"]["noul"] == 0.0, (kill, A.get("sell_route_ok"), sig)
calls = []; Q.jup_quote = lambda mint, amount: (calls.append(1), (None, "x"))[1]
judge({**cand, "dev_pct": None}, "goal", book); assert not calls, "no Jupiter call for a coin that already failed"
print("sell_route_ok gate ok: impact>5% / no route / missing / jupiter down all fail; honeypot killed in judge:", A["sell_route_ok"]["why"])
# ---- one ticket truth: JEV judges the ticket SIZE will actually send ----
thin = {**cand, "liq": 25_000}
Q.jup_quote = lambda mint, amount: (ok_q, None)
assert Q.soft_kill(Q.market(thin, 1000 * config.MODE_RULES["goal"]["size"])) == "liquidity_fits_ticket"   # old uncapped $600 ticket killed it
ok, A, sig, kill = judge(dict(thin), "goal", book)
assert kill != "liquidity_fits_ticket" and A["liquidity_fits_ticket"]["noul"] >= Q.SOFT["liquidity_fits_ticket"][1], (kill, A["liquidity_fits_ticket"])
t = dict(thin); judge(t, "goal", book); assert t["ticket_usd"] == risk.ticket(book, thin, config.MODE_RULES["goal"]["size"] * Q.NO_SOCIAL_CUT)[0] or t["ticket_usd"] == risk.ticket(book, thin, config.MODE_RULES["goal"]["size"])[0]
ok, A, sig, kill = judge({**cand, "liq": 1500}, "goal", book); assert kill == "size_refused", kill                      # SIZE's refusal is the kill
ok, A, sig, kill = judge(dict(thin), "goal", book)
print(f"one ticket truth ok: $25K pool, $1,000 cash → ticket ${t['ticket_usd']:.2f} (was $600 uncapped), liq fit {A['liquidity_fits_ticket']['noul']}, kill {kill}")
print("ALL TESTS PASSED")
