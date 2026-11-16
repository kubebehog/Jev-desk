"""His message formats as text templates, generated from ledger.jsonl only. Every one says PAPER."""
import time
import store

T = lambda ts: time.strftime("%-I:%M %p", time.localtime(ts))  # Asia/Jerusalem box clock


def money(v):
    return ("-" if v < 0 else "") + "${:,.2f}".format(abs(v))


def mc(v):
    if not v: return "?"
    return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.1f}K"


def sell_alert(t):
    """Every-sell alert, e.g. 'Banker · Took profit on Nyajira · +$8.82 (+14.6%) · at $95.2K MC · PAPER'."""
    pnl = t.get("pnl_usd") or 0
    verb = {"Risk": "Stopped out", "Banker": "Took profit on" if pnl >= 0 else "Trailed out of", "Exit": "Sold"}.get(t.get("agent"), "Sold")
    part = "" if t.get("closed") else f" {t.get('frac_of_original', 0)*100:.0f}%"
    pct = f" ({t['pnl_pct']:+.1f}%)" if t.get("pnl_pct") is not None else ""
    at = f" · at {mc(t['mcap'])} MC" if t.get("mcap") else ""
    return f"{t.get('agent','Exit')} · {verb} {t['symbol']}{part} · {'+' if pnl >= 0 else '-'}${abs(pnl):,.2f}{pct} · {t['reason']}{at} · PAPER"


def session_bounds(L, sid=None):
    starts = [x for x in L if x["kind"] == "session_start"]
    s = next((x for x in reversed(starts) if sid is None or x["sid"] == sid), None)
    if not s:
        return None, [x for x in L]
    end = next((x for x in L if x["kind"] == "session_end" and x["sid"] == s["sid"]), None)
    return s, [x for x in L if x["ts"] >= s["ts"] and (end is None or x["ts"] <= end["ts"])]


def stats(L=None, sid=None):
    L = L or store.read_ledger()
    s, W = session_bounds(L, sid)
    trades = [x for x in W if x["kind"] == "trade"]
    closed = [t for t in trades if t["side"] == "SELL" and t.get("closed")]
    wins = [t for t in closed if (t.get("pos_pnl_usd") or 0) > 0]
    eq = [x for x in W if x["kind"] == "equity"]
    scans = [x for x in W if x["kind"] == "scan"]
    start_eq = s["start_equity"] if s else 1000.0
    end_eq = eq[-1]["equity"] if eq else start_eq
    best = max(closed, key=lambda t: t.get("pos_pnl_usd") or 0, default=None)
    return {"session": s, "start_eq": start_eq, "end_eq": end_eq, "fills": len(trades), "closed": len(closed), "wins": len(wins),
            "win_rate": round(100 * len(wins) / len(closed)) if closed else None, "best": best,
            "open": eq[-1]["open"] if eq else 0, "scored": sum(x.get("vetted", 0) for x in scans),
            "start_ts": s["ts"] if s else (L[0]["ts"] if L else time.time()), "end_ts": W[-1]["ts"] if W else time.time(),
            "trades": trades, "realized": round(sum(t.get("pnl_usd") or 0 for t in trades if t["side"] == "SELL"), 2)}


def gaps(ts_list, gap_s=None):
    """Wall-clock holes in a sorted list of timestamps: [(from_ts, to_ts, minutes)] for every step > gap_s."""
    import config
    gap_s = config.GAP_S if gap_s is None else gap_s
    ts = sorted(ts_list)
    return [(a, b, round((b - a) / 60, 1)) for a, b in zip(ts, ts[1:]) if b - a > gap_s]


def coverage(L=None, sid=None):
    """How much of a session the desk was actually running, from the ledger alone: the session_start/end plus every
    equity snapshot (FILLS writes one every 15 s while alive). Returns None when the session isn't in the ledger."""
    L = L if L is not None else store.read_ledger()
    s, W = session_bounds(L, sid)
    if not s: return None
    end = next((x for x in W if x["kind"] == "session_end"), None)
    pts = [s["ts"]] + [x["ts"] for x in W if x["kind"] == "equity" and x.get("sid") in (None, s["sid"])] + ([end["ts"]] if end else [])
    G = gaps(pts)
    total = (max(pts) - s["ts"]) / 60
    gm = sum(b - a for a, b, _ in G) / 60
    return {"sid": s["sid"], "start_ts": s["ts"], "end_ts": max(pts), "sched_min": round((s.get("end_ts", s["ts"]) - s["ts"]) / 60, 1),
            "total_min": round(total, 1), "gap_min": round(gm, 1), "active_min": round(total - gm, 1),
            "pct": round(100 * (total - gm) / total, 1) if total else 100.0, "gaps": G}


def paused_note(L=None, sid=None):
    cv = coverage(L, sid)
    return f" but was only active {cv['active_min']:.0f} of {cv['total_min']:.0f} min (box paused {len(cv['gaps'])}x)" if cv and cv["gaps"] else ""


def morning(L=None, sid=None):
    S = stats(L, sid)
    d = S["end_eq"] - S["start_eq"]
    hrs = (S["end_ts"] - S["start_ts"]) / 3600
    ran = "all night" if hrs >= 5 else f"{hrs*60:.0f} min" if hrs < 1 else f"{hrs:.1f} h"
    ran += paused_note(L, sid)
    return (f"Morning. The desk ran {ran} — {'up' if d >= 0 else 'down'} {money(abs(d))} on your {money(S['start_eq'])} (PAPER). "
            f"{S['closed']} trades closed, {S['wins']} green, {S['open']} still open. Want me to cash out? (paper — nothing to withdraw)")


def two_ways(S, quotes_now, open_qty, L=None):
    """Same coins compared two ways, over each position's whole life (PAPER):
    the desk's exits (all paper sells + open bag marked now) vs buying at the same fills and holding to now."""
    mints = {t["mint"] for t in S["trades"]}
    allt = [x for x in (L or store.read_ledger()) if x["kind"] == "trade" and x["mint"] in mints]
    buys = [t for t in allt if t["side"] == "BUY"]
    if not buys or any(b["mint"] not in quotes_now for b in buys):
        return None
    hc = 0.99 * 0.99  # 1% fee + ~1% slip on the way out
    held = sum(b["qty"] * quotes_now[b["mint"]] * hc for b in buys)
    desk = sum(t["usd"] for t in allt if t["side"] == "SELL") + sum(q * quotes_now[m] * hc for m, q in open_qty.items() if m in mints)
    return {"coins": len(mints), "in": round(sum(b["usd"] for b in buys), 2), "held": round(held, 2), "desk": round(desk, 2)}


def recap(L=None, sid=None, quotes_now=None, open_qty=None):
    S = stats(L, sid)
    best = S["best"]
    mult = S["end_eq"] / S["start_eq"] if S["start_eq"] else 1
    lines = [f"Session recap · {T(S['start_ts'])} → {T(S['end_ts'])} · PAPER",
             f"{money(S['end_eq'])} from {money(S['start_eq'])} · {mult:.2f}x",
             f"Trades {S['closed']} closed ({S['fills']} fills) · {S['wins']} green · win rate {'n/a' if S['win_rate'] is None else str(S['win_rate']) + '%'}",
             f"Best trade {best['symbol'] + ' ' + money(best['pos_pnl_usd']) if best and best['pos_pnl_usd'] > 0 else 'none green yet'}",
             f"Coins scored {S['scored']}"]
    cv = coverage(L, sid)
    if cv:
        lines.append(f"Active {cv['active_min']:.0f} of {cv['total_min']:.0f} min ({cv['pct']:.0f}%) · {len(cv['gaps'])} gap{'s' if len(cv['gaps']) != 1 else ''}"
                     + (f" (box paused {cv['gap_min']:.0f} min: no scanning, no stops watched)" if cv["gaps"] else ""))
    tw = two_ways(S, quotes_now, open_qty or {}, L) if quotes_now is not None else None
    if tw:
        lines.append(f"Same {tw['coins']} coins two ways, {money(tw['in'])} in: desk's exits {money(tw['desk'])} · bought at the same fills and held {money(tw['held'])}")
    return "\n".join(lines)


def lock_line(L=None):
    S = stats(L)
    last = next((t for t in reversed(S["trades"]) if t["side"] == "SELL"), None)
    return f"Trading Desk · {money(S['end_eq'])} · {S['end_eq']/S['start_eq']:.2f}x" + (f" · {sell_alert(last)}" if last else "")


def jev_morning(L=None, sid=None, jev=None):
    """JEV's morning line. JEV doesn't write prose: every word here is a template, every number is from the ledger."""
    S = stats(L, sid)
    d = S["end_eq"] - S["start_eq"]
    hrs = (S["end_ts"] - S["start_ts"]) / 3600
    ran = "all night" if hrs >= 5 else f"{hrs*60:.0f} min" if hrs < 1 else f"{hrs:.1f} h"
    ran += paused_note(L, sid)
    j = f" Judged {jev.judged} · approved {jev.approved} · vetoed {jev.vetoed}." if jev else ""
    return (f"JEV · Morning. The desk ran {ran} — {'up' if d >= 0 else 'down'} {money(abs(d))} on your {money(S['start_eq'])} (PAPER). "
            f"{S['closed']} trades closed, {S['wins']} green, {S['open']} still open.{j} Want me to cash out? (paper — nothing to withdraw)")
