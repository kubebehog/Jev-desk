"""RISK / BANKER / EXIT: per-mode exits straight from his rule blocks (config.MODE_RULES)."""
import config, executor, store


def rules(mode):
    return config.MODE_RULES.get(mode, config.MODE_RULES["goal"])


def decide(pos, row, track):
    """RISK's one rule as a pure decision (no selling here): returns ([(frac, why, agent)], notes).
    `track` holds peak / tp_done / stop_at_entry; the RISK bot keeps it in its own memory, manage() uses the position."""
    R = rules(pos["mode"])
    q, liq = row["price"], row["liq"]
    track["peak"] = max(track.get("peak") or pos["peak"], q)
    track.setdefault("tp_done", pos.get("tp_done", 0))
    pct = (q / pos["entry_fill"] - 1) * 100
    notes = []
    if R.get("breakeven") and pct > 0 and not track.get("stop_at_entry"):
        track["stop_at_entry"] = True
        notes.append(f"{pos['symbol']} stop moved to entry")
    stop = 0.0 if track.get("stop_at_entry") else R["stop"]
    if pct <= stop:
        return [(1.0, f"stop {stop:+.0f}%" + (" (at entry)" if stop == 0 else ""), "Risk")], notes
    vr = config.RISK_VOL_DECAY_RATIO
    if vr and row.get("vol_h24") and row.get("vol_h6") is not None:   # his RISK rule: 6h volume < 20% of the 24h average → close
        ratio = row["vol_h6"] / (row["vol_h24"] / 4)
        if ratio < vr:
            return [(1.0, f"volume dying: 6h at {ratio:.2f}x the 24h average (< {vr:.2f})", "Risk")], notes
    if pos["mode"] == "fix-bags" and (liq < config.MIN_LIQ_USD or row.get("vol_h1", 1) < 500):
        return [(1.0, "dead bag, sold now", "Exit")], notes
    acts, ladder = [], R.get("ladder") or []
    while track["tp_done"] < len(ladder) and pct >= ladder[track["tp_done"]][0]:
        lvl, frac = ladder[track["tp_done"]]
        track["tp_done"] += 1
        acts.append((frac, f"sold {frac*100:.0f}% at x{1 + lvl/100:.1f}", "Exit"))
    trail = R["trail"]
    if track["peak"] > pos["entry_fill"] and q <= track["peak"] * (1 - trail / 100):
        acts.append((1.0, f"trail {trail:.0f}% from top", "Banker"))
    return acts, notes


def manage(state, quotes):
    """Single-process form of RISK (used by tests and `close-all` paths): decide, then sell through the executor."""
    acts = []
    for mint in list(state["positions"]):
        pos, row = state["positions"][mint], quotes.get(mint)
        if not row or row["price"] <= 0:
            store.log("risk", f"{pos['symbol']}: no live quote this tick, holding (cannot verify price)")
            continue
        todo, notes = decide(pos, row, pos)
        for n in notes: store.log("risk", n, alert=True)
        for frac, why, agent in todo:
            if mint in state["positions"]:
                executor.paper_sell(state, mint, frac, row["price"], row["liq"], why, agent=agent, mcap=row.get("mcap")); acts.append(why)
    return acts


def equity(state, quotes):
    v = state["cash"] + state.get("vault", 0.0)
    for m, p in state["positions"].items():
        r = quotes.get(m)
        v += executor.mark_value(p, r["price"], r["liq"]) if r else p["cost_usd"] * p["qty"] / p["qty0"]
    return round(v, 4)


def piggy(state):
    """Compounder lock: when free cash reaches lock_at x start, the start goes in the vault for good."""
    R = rules(state["mode"])
    if R.get("lock_at") and not state.get("vault") and state["cash"] >= R["lock_at"] * state["session"]["start_equity"]:
        state["vault"] = round(state["session"]["start_equity"], 2)
        state["cash"] -= state["vault"]
        store.log("piggy", f"cash hit {R['lock_at']:.0f}x, ${state['vault']:.2f} locked in the vault, only house money rides", alert=True)


def goal_check(state, quotes, eq):
    s = state.get("session") or {}
    goal = s.get("goal_usd")
    if not goal or eq < goal:
        return False
    if state["mode"] == "goal":
        for m in list(state["positions"]):
            r = quotes.get(m)
            if r:
                executor.paper_sell(state, m, 1.0, r["price"], r["liq"], "goal hit, Exit sells everything", agent="Exit", mcap=r.get("mcap"))
        state["halted"] = True
        store.log("exit", f"Goal hit · desk off · ${eq:,.2f} PAPER", alert=True)
        return True
    if not s.get("line_beaten"):
        s["line_beaten"] = True
        store.log("chief", f"line to beat ${goal:,.2f} beaten, still running until clock-out", alert=True)
    return False


def ticket(state, row, size_frac):
    """Entry size after the RESEARCH.md guards. Returns (usd, None) or (0, why-skipped)."""
    usd = state["cash"] * size_frac
    if not config.ENTRY_GUARDS:
        return usd, None
    usd = min(usd, state["cash"] * config.SIZE_CAP, (row.get("liq") or 0) * config.MAX_TICKET_PCT_OF_LIQ / 100)
    chg = row.get("chg_h1")
    if config.MAX_ENTRY_CHG_H1 is not None and chg is not None and chg > config.MAX_ENTRY_CHG_H1:
        return 0, f"already +{chg:.0f}% in 1h (anti-chase > {config.MAX_ENTRY_CHG_H1}%)"
    if usd < config.MIN_TICKET_USD:
        return 0, f"ticket ${usd:.2f} after caps is under ${config.MIN_TICKET_USD:.0f} (liq ${row.get('liq') or 0:,.0f})"
    sp = executor.slip_pct(usd, row.get("liq") or 0)
    if sp > config.MAX_ENTRY_SLIP_PCT:
        return 0, f"modeled slippage {sp:.2f}% > {config.MAX_ENTRY_SLIP_PCT}%"
    return round(usd, 2), None
