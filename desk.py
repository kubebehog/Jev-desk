"""DESK - PAPER ONLY Solana memecoin desk, a copy of @Hrundel75's desk rules.
  python3 desk.py setup "trade overnight $500 degen" [--fresh] [--foreground]   JEV (chief): sentence -> setup card -> session
  python3 desk.py start --minutes 20 [--mode goal] [--goal 2000]             start a session (always has an end time)
  python3 desk.py stop [--sell-all]                                         stop the running session ("Stop & sell all")
  python3 desk.py pick <mint> <usd>                                         sell-for-me: you pick, Exit sells
  python3 desk.py scan | status | messages | bus [N] | push on|off|test
  python3 desk.py coverage <sid> [--backfill]                               active vs paused minutes from the ledger (--backfill: append missing 'gap' entries, idempotent)
A session is JEV + 7 seat processes (SCAN VET SOCIAL SIZE FILLS RISK PIGGY) talking on bus.db, see BOTS_SPEC.md.
"""
import argparse, datetime as dt, json, os, subprocess, sys, time
import config, store, scanner, analyst, signals, executor, risk, sources, chief, messages, notify, market

VET_LIMIT = 30
STOPFLAG = os.path.join(store.HERE, "STOP")


def migrate(state):
    state.setdefault("vault", 0.0); state.setdefault("session", None); state.setdefault("nights", 0)
    return state


def candles(pair):
    try:
        j = sources.get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute?aggregate=5&limit=48")
        return [[c[0], c[1], c[2], c[3], c[4], round(c[5])] for c in reversed(j["data"]["attributes"]["ohlcv_list"])]
    except Exception:  # noqa
        return None


def scan_pass(state, pp=None, trade=False):
    rows, feeds = scanner.scan(pp)
    picks = set(state.get("picks") or []) | ({state["one_coin"]} if state.get("one_coin") else set())
    pool = [r for r in rows if r["mint"] in picks or "ds_cto" in r["feeds"]] + sorted([r for r in rows if r["liq"] >= config.MIN_LIQ_USD], key=lambda r: -(r["vol_h1"] or 0))
    seen, vetted = set(), []
    for r in pool:
        if r["mint"] in seen or len(vetted) >= VET_LIMIT:
            continue
        seen.add(r["mint"])
        try:
            v = analyst.vet(r, pp)
        except Exception as e:  # noqa
            store.log("analyst", f"{r['symbol']}: vet error {str(e)[:60]} -> UNKNOWN/fail"); continue
        signals.record_holders(state, r["mint"], v["holders"])
        vetted.append({**r, "vet": v["checks"], "passed": v["passed"], "hard_ok": v["passed"], "holders": v["holders"], "dev_pct": v["dev_pct"], "decimals": v.get("decimals")})
        time.sleep(0.3)
    analyst.soft_scores(vetted)
    for v in vetted:
        ok, sig = signals.should_enter(state["mode"], v, {"passed": v["passed"], "dev_pct": v["dev_pct"]}, state, pp)
        v["signal"], v["enter"] = sig, ok
    for v in sorted(vetted, key=lambda v: (-v["passed"], -(v["vol_h1"] or 0)))[:5]:
        v["candles"] = candles(v["pair"]) if v.get("pair") else None
    n_pass = sum(v["passed"] for v in vetted)
    store.append("scan", mode=state["mode"], feeds=feeds, universe=len(rows), vetted=len(vetted), passed=n_pass, candidates=vetted)
    store.log("scan", f"{len(rows)} scanned · {len(vetted)} vetted · {n_pass} pass hard+soft")
    if trade and not state["halted"]:
        enter(state, vetted)
    return vetted


def enter(state, vetted):
    mode, R = state["mode"], config.MODE_RULES[state["mode"]]
    if mode in ("sell-for-me", "one-coin"):
        return  # you pick / one-coin has its own loop
    cands = [v for v in vetted if v["enter"] and v["mint"] not in state["positions"]]
    for c in sorted(cands, key=lambda v: -v["vol_m5"]):
        if len(state["positions"]) >= R["max_open"]:
            store.log("size", f"{c['symbol']} passed but {R['max_open']}/{R['max_open']} open"); continue
        usd, why = risk.ticket(state, c, R["size"])
        if why:
            store.log("size", f"{c['symbol']} passed but skipped: {why}"); continue
        executor.paper_buy(state, c, usd, f"{mode}: hard+soft PASS, signal PASS", mode)
    if not cands:
        store.log("vet", "no entry: nothing passed every hard + soft check and the signal (UNKNOWN = fail)")


def one_coin_tick(state, quotes):
    m = state.get("one_coin"); r = quotes.get(m) if m else None
    if not r: return
    h = state["price_hist"].setdefault(m, []); h.append([time.time(), r["price"]]); del h[:-120]
    px = [p for _, p in h]
    if len(px) < 10: return
    lo, hi = min(px), max(px)
    if m not in state["positions"] and r["price"] <= lo * 1.02 and hi > lo * 1.04:
        usd, why = risk.ticket(state, r, 1.0)
        if why: store.log("size", f"one-coin {r.get('symbol')} skipped: {why}"); return
        executor.paper_buy(state, r, usd, "one-coin: bought support", "one-coin")
    elif m in state["positions"] and r["price"] >= hi * 0.98 and r["price"] > state["positions"][m]["entry_fill"] * 1.02:
        executor.paper_sell(state, m, 1.0, r["price"], r["liq"], "sold into resistance", agent="Exit", mcap=r.get("mcap"))


def quotes_for(mints):
    return market.quotes(mints)


def snapshot(state, quotes, note=""):
    eq = risk.equity(state, quotes)
    store.append("equity", equity=eq, cash=round(state["cash"], 4), vault=state.get("vault", 0), open=len(state["positions"]),
                 sid=(state.get("session") or {}).get("sid"),
                 positions={m: {"symbol": p["symbol"], "qty": p["qty"], "quote": (quotes.get(m) or {}).get("price"), "mcap": (quotes.get(m) or {}).get("mcap"),
                                "mode": p["mode"], "stop_at_entry": p.get("stop_at_entry", False)} for m, p in state["positions"].items()}, note=note)
    return eq


def new_session(state, kind, end_ts, mode=None, goal=None, setup=None):
    q = quotes_for(set(state["positions"]))
    state["nights"] = state.get("nights", 0) + 1
    if mode: state["mode"] = mode
    sid = time.strftime("%Y%m%d-%H%M")
    state["session"] = {"sid": sid, "night": state["nights"], "kind": kind, "start_ts": time.time(), "end_ts": end_ts,
                        "start_equity": risk.equity(state, q), "goal_usd": goal, "mode": state["mode"]}
    state["halted"] = False
    store.append("session_start", sid=sid, night=state["nights"], session_kind=kind, mode=state["mode"], end_ts=end_ts,
                 start_equity=state["session"]["start_equity"], goal_usd=goal, setup=setup)
    store.save_state(state)
    return sid


def flatten(state, reason):
    """Sell every open paper position at the live quote (normal slip+fee path). Returns mints left open (no quote)."""
    if not state["positions"]:
        return []
    q = quotes_for(set(state["positions"]))
    for m in list(state["positions"]):
        if m in q and q[m]["price"] > 0:
            executor.paper_sell(state, m, 1.0, q[m]["price"], q[m]["liq"], reason, agent="Exit", mcap=q[m].get("mcap"))
    left = list(state["positions"])
    if left:
        store.log("exit", f"could not flatten {len(left)} position(s): no live quote", alert=True)
    store.save_state(state)
    return left


def session_running(state):
    S = state.get("session") or {}
    pid = S.get("pid")
    if not pid or time.time() > S.get("end_ts", 0):
        return False
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


CLOUD_MARK = os.path.join(store.HERE, "cloud_run.json")


def refuse_orphans(state):
    """No paper position may stay open without a session watching it. No local session while a cloud one owns the book."""
    if os.path.exists(CLOUD_MARK) and not os.environ.get("DESK_CLOUD"):
        sys.exit("refusing: a cloud session owns the book (cloud_run.json). `python3 cloud.py status`, then `python3 cloud.py pull` once it's done.")
    if state["positions"] and not session_running(state):
        sys.exit(f"refusing: {len(state['positions'])} paper position(s) open with no session watching. "
                 "Run `python3 desk.py close-all` first.")
    if session_running(state):
        sys.exit("refusing: a session is already running; `python3 desk.py stop` it first.")


def run(sid, tick=None, inline=None):
    """The session = JEV + seven seat processes on the bus (bots/). JEV flattens through FILLS on every exit path."""
    from bots import jev
    jev.supervise(sid, STOPFLAG, inline=inline, tick=tick)


def end_session(state, why):
    flatten(state, f"session end ({why}): flatten, no session watching")
    q = quotes_for(set(state["positions"]))
    eq = snapshot(state, q, note="session end")
    S = state["session"]
    store.append("session_end", sid=S["sid"], why=why, equity=eq)
    L = store.read_ledger()
    traded = {t["mint"] for t in L if t["kind"] == "trade" and t["ts"] >= S["start_ts"] - 1}
    allq = quotes_for(traded | set(state["positions"]))
    open_qty = {m: p["qty"] for m, p in state["positions"].items()}
    rc = messages.recap(L, S["sid"], {m: v["price"] for m, v in allq.items()}, open_qty)
    mo = messages.morning(L, S["sid"])
    store.append("recap", sid=S["sid"], text=rc, morning=mo, quotes_now={m: v["price"] for m, v in allq.items()})
    notify.push(rc, title="Trading Desk · session recap · PAPER")
    store.log("chief", f"session over ({why}) · paper equity ${eq:,.2f}")
    print(rc); print(mo)
    store.save_state(state)


def judge_report(state, vetted):
    """Read-only: what JEV's questions + the sell_route_ok gate would say about this scan's VET survivors. No orders."""
    from bots.jev import judge
    for r in [v for v in vetted if v["passed"]]:
        r = dict(r); ok, A, sig, kill = judge(r, state["mode"], state)
        sr = A.get("sell_route_ok")
        print(f"JEV {r['symbol']:<10} {r['mint']} ticket ${r.get('ticket_usd') or 0:,.2f} → {'PASS' if ok else 'no entry: ' + kill}"
              + (f" · sell_route_ok {sr['noul']} · impact {sr['impact']} · {sr['why']}" if sr else " · sell_route_ok not asked (failed earlier)"))
    if not any(v["passed"] for v in vetted): print("JEV: nothing passed VET hard+soft this scan, sell_route_ok not asked")


def coverage(sid, backfill=False):
    """Offline: gaps in a past session from its ledger equity timestamps. --backfill appends one 'gap' entry per gap
    not already in the ledger (same sid + from_ts), so running it twice adds nothing."""
    L = store.read_ledger(); cv = messages.coverage(L, sid)
    if not cv or cv["sid"] != sid: sys.exit(f"no session {sid} in the ledger")
    have = {(x.get("sid"), round(x["from_ts"], 3)) for x in L if x["kind"] == "gap"}
    added = 0
    for a, b, mins in cv["gaps"]:
        if backfill and (sid, round(a, 3)) not in have:
            store.append("gap", sid=sid, from_ts=round(a, 3), to_ts=round(b, 3), minutes=mins, backfill=True); added += 1
    T = lambda t: time.strftime("%H:%M:%S", time.localtime(t))
    print(f"session {sid}: scheduled {cv['sched_min']:.1f} min · ran {T(cv['start_ts'])} → {T(cv['end_ts'])} ({cv['total_min']:.1f} min)"
          f" · active {cv['active_min']:.1f} of {cv['total_min']:.1f} min ({cv['pct']:.1f}%) · {len(cv['gaps'])} gaps ({cv['gap_min']:.1f} min)")
    for a, b, mins in cv["gaps"]: print(f"  gap {T(a)} → {T(b)} · {mins:.1f} min (box paused: no scanning, no stops watched)")
    if backfill: print(f"backfill: {added} gap entr{'y' if added == 1 else 'ies'} appended ({len(cv['gaps']) - added} already present)")
    return cv


def spawn(sid):
    log = open(os.path.join(store.HERE, f"session-{sid}.log"), "a")
    p = subprocess.Popen([sys.executable, "-u", os.path.abspath(__file__), "run", sid], stdout=log, stderr=log, cwd=store.HERE, start_new_session=True)
    print(f"session {sid} running in background, pid {p.pid}, log session-{sid}.log")


def resolve_symbol(sym):
    j = sources.get(sources.DS + "/latest/dex/search?q=" + sym)
    ps = [p for p in j.get("pairs") or [] if p.get("chainId") == "solana" and (p["baseToken"].get("symbol") or "").upper() == sym.upper()]
    return max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)["baseToken"]["address"] if ps else None


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    for c in ("scan", "status", "messages"): sp.add_parser(c)
    sb = sp.add_parser("bus"); sb.add_argument("n", nargs="?", type=int, default=40)
    s1 = sp.add_parser("setup"); s1.add_argument("sentence"); s1.add_argument("--fresh", action="store_true"); s1.add_argument("--foreground", action="store_true")
    s1.add_argument("--goal", type=float); s1.add_argument("--dry", action="store_true")
    s2 = sp.add_parser("start"); s2.add_argument("--minutes", type=float, required=True); s2.add_argument("--mode", choices=config.MODES); s2.add_argument("--goal", type=float)
    s2.add_argument("--foreground", action="store_true")
    s3 = sp.add_parser("stop"); s3.add_argument("--sell-all", action="store_true")
    s4 = sp.add_parser("pick"); s4.add_argument("mint"); s4.add_argument("usd", type=float)
    s5 = sp.add_parser("push"); s5.add_argument("what", choices=["on", "off", "test", "topic"])
    s6 = sp.add_parser("run"); s6.add_argument("sid")
    s7 = sp.add_parser("close-all"); s7.add_argument("--reason", default="flatten: no session watching")
    s8 = sp.add_parser("coverage"); s8.add_argument("sid"); s8.add_argument("--backfill", action="store_true")
    a = ap.parse_args()
    state = migrate(store.load_state())
    if a.cmd == "coverage":
        return coverage(a.sid, a.backfill)
    if a.cmd == "scan":
        pp = sources.PumpPortal(); time.sleep(15); vetted = scan_pass(state, pp); store.save_state(state)
        judge_report(state, vetted)
    elif a.cmd == "close-all":
        if session_running(state): sys.exit("a session is running; use `desk.py stop` (it flattens on exit)")
        left = flatten(state, a.reason)
        print(f"closed; open now: {len(left)} · cash ${state['cash']:,.2f}")
    elif a.cmd == "setup":
        c = chief.parse(a.sentence)
        if not a.dry: refuse_orphans(state)
        if a.goal: c["goal_usd"] = a.goal
        eq = risk.equity(state, quotes_for(set(state["positions"])))
        print(chief.card(c, eq))
        if a.dry: return
        store.append("setup", **{k: v for k, v in c.items()})
        if a.fresh and c["budget"] and not state["positions"]:
            state["cash"] = c["budget"]; state["vault"] = 0.0
            store.append("bankroll", cash=c["budget"], note="fresh paper bankroll from setup")
        if c["mode"] == "one-coin" and c["coin"]:
            state["one_coin"] = resolve_symbol(c["coin"])
        sid = new_session(state, c["session"], c["end_ts"], c["mode"], c["goal_usd"], setup=c)
        run(sid) if a.foreground else spawn(sid)
    elif a.cmd == "start":
        refuse_orphans(state)
        end = time.time() + min(a.minutes, config.MAX_SESSION_HOURS * 60) * 60
        sid = new_session(state, "custom", end, a.mode, a.goal or (state["session"] or {}).get("goal_usd"))
        run(sid) if a.foreground else spawn(sid)
    elif a.cmd == "run":
        run(a.sid)
    elif a.cmd == "stop":
        open(STOPFLAG, "w").write("sell-all" if a.sell_all else "stop"); print("stop requested" + (" + sell all" if a.sell_all else ""))
    elif a.cmd == "pick":
        if not session_running(state): sys.exit("refusing: picks need a running session to watch them (setup/start one first)")
        from bots import bus
        bus.post(state["session"]["sid"], "You", "JEV", "pick", f"You · pick {a.mint[:6]}… ${a.usd:,.2f} → JEV", {"mint": a.mint, "usd": a.usd}, task=a.mint)
        print("pick handed to JEV on the bus")
    elif a.cmd == "push":
        if a.what == "test": print(notify.push("Trading Desk test · PAPER"))
        elif a.what == "topic": print(notify.cfg())
        else: print(notify.set_enabled(a.what == "on"))
    elif a.cmd == "messages":
        L = store.read_ledger(); r = [x for x in L if x["kind"] == "recap"]
        print(messages.morning(L)); print(); print(r[-1]["text"] if r else messages.recap(L)); print()
        for t in [x for x in L if x["kind"] == "trade" and x["side"] == "SELL"][-5:]: print(messages.sell_alert(t))
    elif a.cmd == "bus":
        from bots import bus
        for m in bus.recent(a.n): print(time.strftime("%H:%M:%S", time.localtime(m["ts"])), f"{m['frm']:>6} → {m['to']:<6} {m['type']:<11}", m["text"])
        for n, b in sorted(bus.beats().items()): print(f"  ♥ {n:<6} {b['status']:<14} {time.time() - b['ts']:5.0f}s ago · {b['last'][:90]}")
    elif a.cmd == "status":
        print({k: state.get(k) for k in ("mode", "cash", "vault", "halted", "session")}, list(state["positions"]))


if __name__ == "__main__":
    main()
