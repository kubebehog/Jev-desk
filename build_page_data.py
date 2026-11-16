"""Regenerate every number on the Page from ledger.jsonl (+ notify.json topic) -> page_data_min.json.
Usage: python3 build_page_data.py ; then replace the Page's DATA constant with page_data_min.json."""
import json, math, os, time
import store, config, messages

LT = lambda ts, f="%H:%M": time.strftime(f, time.localtime(ts))          # Asia/Jerusalem (box clock)
UT = lambda ts: time.strftime("%H:%M", time.gmtime(ts))
r2 = lambda v: None if v is None else round(v, 2)


def k(v):
    if v is None: return "?"
    return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.0f}K" if v >= 1e3 else f"${v:.0f}"


def build():
    L = store.read_ledger()
    start = next(x for x in L if x["kind"] == "start")
    eqs = [x for x in L if x["kind"] == "equity"]
    trades = [x for x in L if x["kind"] == "trade"]
    scans = [x for x in L if x["kind"] == "scan"]
    sess = [x for x in L if x["kind"] == "session_start"]
    ends = {x["sid"]: x for x in L if x["kind"] == "session_end"}
    recaps = [x for x in L if x["kind"] == "recap"]
    S = sess[-1] if sess else None
    live = bool(S and S["sid"] not in ends and time.time() < S["end_ts"])
    bal = eqs[-1]["equity"] if eqs else start["start_usd"]
    s0 = start["start_usd"]
    ss = S["start_equity"] if S else s0
    series = [[round(start["ts"]), s0]] + [[round(e["ts"]), round(e["equity"], 2)] for e in eqs]
    st = max(1, len(series) // 300); series = series[::st] + ([series[-1]] if series[-1] not in series[::st] else [])
    # markers with his chip labels
    marks = []
    for t in trades:
        if t["side"] == "BUY":
            lab = f"Bought {t['symbol']}"
        elif t.get("agent") == "Risk" or (t.get("pnl_usd") or 0) < 0:
            lab = f"{t.get('pnl_pct', 0):+.0f}%"
        else:
            lab = f"+${t.get('pnl_usd', 0):,.2f}"
        marks.append([round(t["ts"]), t["side"][0], t["symbol"], round(t["usd"], 2), r2(t.get("pnl_usd")), t.get("agent") or ("Sniper" if t["side"] == "BUY" else "Exit"), t["reason"], lab, k(t.get("mcap"))])
    # positions
    last = eqs[-1] if eqs else {"positions": {}, "cash": s0}
    buys = {t["mint"]: t for t in trades if t["side"] == "BUY"}
    pos = []
    for m, p in last["positions"].items():
        b = buys.get(m, {}); val = (p["qty"] * p["quote"]) if p.get("quote") else None
        basis = b.get("usd", 0) * p["qty"] / b["qty"] if b.get("qty") else None
        pos.append({"sym": p["symbol"], "value": r2(val), "basis": r2(basis), "pnl": r2(val - basis) if val and basis else None,
                    "pct": r2((p["quote"] / b["fill"] - 1) * 100) if p.get("quote") and b.get("fill") else None, "mcap": k(p.get("mcap")),
                    "badge": "stop at entry" if p.get("stop_at_entry") else f"stop {config.MODE_RULES.get(p.get('mode','goal'), config.MODE_RULES['goal'])['stop']}%"})
    act = []
    for t in reversed(trades[-14:]):
        if t["side"] == "BUY": title, sub = f"Bought {t['symbol']}", f"{t.get('agent') or 'Sniper'} · {LT(t['ts'])}"
        else:
            verb = "Stopped" if t.get("agent") == "Risk" else "Sold"
            title, sub = f"{verb} {t['symbol']}", f"{t.get('agent') or 'Exit'} · {t['reason']} · {LT(t['ts'])}"
        act.append([title, sub, round(t["usd"], 2), r2(t.get("pnl_usd")), k(t.get("mcap")), t["side"][0]])
    st_ = messages.stats(L)
    closed = [t for t in trades if t["side"] == "SELL" and t.get("closed")]
    wins = [t for t in closed if (t.get("pos_pnl_usd") or 0) > 0]
    best = max(closed, key=lambda t: t.get("pos_pnl_usd") or -1e9, default=None)
    sells = [t for t in trades if t["side"] == "SELL"]
    lastsell = sells[-1] if sells else None
    # SOFT panel: JEV's typed answers against his thresholds.py lines when JEV asked; else VET's three soft numbers
    from bots import questions as Q
    def jev_soft(c):
        A = c.get("answers") or {}
        if "shape" in A:
            rows = [["crowd (shape)", A["shape"]["probabilities"]["crowd"], Q.SHAPE_MIN_CROWD, "min"]]
            rows += [[n, A[n].get("noul"), lim, d] for n, (d, lim) in Q.SOFT.items() if n in A]
            return rows
        return [[n, (c.get("soft") or {}).get(n), config.SOFT_MAX[n], "max"] for n in config.SOFT_MAX]
    # scanner
    sc = scans[-1] if scans else {"candidates": [], "feeds": {}, "universe": 0, "vetted": 0, "passed": 0}
    C = sc["candidates"]
    feat = [c for c in C if c.get("candles")]
    feat.sort(key=lambda c: (-c["passed"], -(c["vol_h1"] or 0)))
    tabs = []
    sig = lambda x: float(f"{x:.4g}")
    for c in feat[:3]:
        tabs.append({"sym": c["symbol"], "age": c.get("age_h"), "mcap": k(c["mcap"]), "liq": k(c["liq"]), "holders": c.get("holders"),
                     "h1": c.get("chg_h1"), "passed": c["passed"], "candles": [[sig(x[1]), sig(x[2]), sig(x[3]), sig(x[4]), x[5]] for x in c["candles"][-30:]],
                     "panel": c.get("panel", []),
                     "hard": [[v["check"], v["verdict"], v.get("value")] for v in c["vet"]],
                     "soft": jev_soft(c)})
    hard_counts = {}
    for c in C:
        for v in c["vet"]:
            d = hard_counts.setdefault(v["check"], [0, 0, 0]); d[["PASS", "FAIL", "UNKNOWN"].index(v["verdict"])] += 1
    table = [[c["symbol"], round(c["liq"]), round(c["mcap"] or 0), round(c["vol_h1"] or 0), r2(c.get("chg_h1")), int(c["passed"]),
              "".join(v["verdict"][0] for v in c["vet"]), "".join(s["verdict"][0] for s in c.get("signal", [])), ",".join(f.replace("ds_", "") for f in c["feeds"])] for c in C][:20]
    # desk log in his format: "fills · buy #1 · in at $214k"
    log, nb, ns = [], 0, 0
    for t in trades:
        if t["side"] == "BUY":
            nb += 1; log.append([LT(t["ts"]), f"fills · buy #{nb} · {t['symbol']} · in at {k(t.get('mcap'))}", "BUY"])
        else:
            ns += 1; log.append([LT(t["ts"]), f"{(t.get('agent') or 'exit').lower()} · sell #{ns} · {t['symbol']} · out at {k(t.get('mcap'))} · {t['reason']}", f"{t.get('pnl_usd', 0):+,.2f}"])
    for x in [x for x in L if x["kind"] == "log" and x.get("agent") in ("scan", "vet", "chief", "risk", "piggy", "size", "exit")][-14:]:
        log.append([LT(x["ts"]), f"{x['agent']} · {x['msg']}", ""])
    log.sort(key=lambda r: r[0]); log = log[-18:][::-1]
    # 8 OINK cards
    vault = last.get("vault", 0) or 0
    soft_avg = lambda n: r2(sum((c.get("soft") or {}).get(n) or 0 for c in C) / max(1, len(C)))
    wl = f"{len(wins)}W {len(closed)-len(wins)}L"
    cards = [
        ["CHIEF", "setup · picks the mode", "mode", (S or {}).get("mode", "goal"), 1.0, f'"{(S or {}).get("setup", {}) and (S.get("setup") or {}).get("sentence", "") or "no sentence, started by command"}"'],
        ["SCAN", "what moves", "scanned", str(sc["universe"]), min(1, sc["universe"] / 200), f'"{sc["vetted"]} with liq ≥ $20K went to VET"'],
        ["VET", "is it real", "pass rate", f"{sc['passed']}/{sc['vetted']}", sc["passed"] / max(1, sc["vetted"]), f'"{hard_counts.get("not bundled (proxy)", [0,0,0])[1]} bundled, {hard_counts.get("vol 1h >= $25K", [0,0,0])[1]} too quiet"'],
        ["SOCIAL", "who's talking", "with socials", f"{sum(1 for c in C if c.get('socials'))}/{len(C)}", sum(1 for c in C if c.get("socials")) / max(1, len(C)), '"links only, no post reading"'],
        ["SIZE", "how much", "ticket", f"${(buys[list(buys)[-1]]['usd'] if buys else 0):,.0f}", config.MODE_RULES[(S or {}).get("mode", "goal")]["size"], f'"{config.MODE_RULES[(S or {}).get("mode", "goal")]["size"]*100:.0f}% of free cash, never more"'],
        ["FILLS", "execution", "last fill", (f"{lastsell['side']} #{ns}" if lastsell else (f"BUY #{nb}" if nb else "none")), min(1, len(trades) / 10), f'"paper, live quote + slip + 1% fee"'],
        ["RISK", "closing", "closed", wl, (len(wins) / len(closed)) if closed else 0, '"stop −18%, trail 12% once green"'],
        ["PIGGY", "guards the vault", "vault", f"${vault:,.0f}", min(1, vault / max(1, ss)), '"oink"' if vault else '"locks the start at 2x (compound mode)"'],
    ]
    # the bus: what the seats said to each other this session (bots/bus.py), and each seat's heartbeat
    chat, beats = [], {}
    try:
        from bots import bus
        sid = (S or {}).get("sid")
        chat = [[LT(m["ts"]), m["frm"], m["to"], m["type"], m["text"]] for m in bus.recent(70, sid=sid) if m["type"] != "hello" or len(chat) < 70]
        now = time.time()
        beats = {n: {"status": b["status"], "age": round(now - b["ts"]), "last": b["last"], "n": b["n"], "live": b["sid"] == sid and now - b["ts"] < 60 and b["status"] != "off"}
                 for n, b in bus.beats().items() if b["sid"] == sid}
    except Exception:  # noqa  no bus yet
        pass
    seat = {"CHIEF": "JEV"}
    said = lambda n: next((c[4] for c in reversed(chat) if c[1] == seat.get(n, n) and c[3] not in ("hello",)), None)
    subs = {"CHIEF": "jev · picks, never trades", "SCAN": "paper bot · what moves", "VET": "paper bot · is it real", "SOCIAL": "paper bot · who's talking",
            "SIZE": "how much", "FILLS": "execution", "RISK": "closing", "PIGGY": "guards the vault"}
    for c in cards:
        c[1] = subs.get(c[0], c[1])
        q = said(c[0])
        if q: c[5] = '"' + q + '"'
        b = beats.get(seat.get(c[0], c[0])) or {}
        c += [b.get("status", "off"), b.get("age"), bool(b.get("live"))]
    two = recaps[-1]["text"].split("\n")[-1] if recaps and "two ways" in recaps[-1]["text"] else None
    nt = json.load(open(os.path.join(store.HERE, "notify.json"))) if os.path.exists(os.path.join(store.HERE, "notify.json")) else {}
    return {
        "generated": LT(time.time(), "%Y-%m-%d %H:%M"), "utc": UT(eqs[-1]["ts"] if eqs else time.time()),
        "live": live, "night": (S or {}).get("night", 1), "kind": (S or {}).get("session_kind", "custom"), "mode": (S or {}).get("mode", "goal"),
        "sess_start": LT(S["ts"]) if S else None, "sess_end": LT(S["end_ts"]) if S else None, "goal": (S or {}).get("goal_usd"),
        "start_usd": s0, "sess_start_eq": r2(ss), "balance": r2(bal), "change": r2(bal - s0), "change_pct": r2((bal / s0 - 1) * 100), "mult": round(bal / s0, 2),
        "sess_change": r2(bal - ss), "cash": r2(last.get("cash")), "vault": vault,
        "progress": round((math.log10(max(bal, 100)) - 2) / 3 * 100, 1),
        "series": series, "markers": marks, "positions": pos, "activity": act,
        "recap": {"closed": len(closed), "fills": len(trades), "wins": len(wins), "win_rate": round(100 * len(wins) / len(closed)) if closed else None,
                  "best": [best["symbol"], r2(best["pos_pnl_usd"])] if best and (best.get("pos_pnl_usd") or 0) > 0 else None,
                  "worst": [min(closed, key=lambda t: t.get("pos_pnl_usd") or 0)["symbol"], r2(min(t.get("pos_pnl_usd") or 0 for t in closed))] if closed else None,
                  "scored": sum(s.get("vetted", 0) for s in scans), "scans": len(scans), "realized": r2(sum(t.get("pnl_usd") or 0 for t in sells)), "two_ways": two},
        "bots": [["Sniper", f"{nb} buys", f"last: {next((t['symbol'] for t in reversed(trades) if t['side']=='BUY'), '—')}", "Filled · paper"],
                 ["Risk", "Guarding" if pos else "Idle", f"stops: {sum(1 for t in sells if t.get('agent')=='Risk')}", "stop −18% · trail 12%"],
                 ["Banker", f"{sum(1 for t in sells if t.get('agent')=='Banker')} take-profits", f"realized {sum(t.get('pnl_usd') or 0 for t in sells):+,.2f}", "trail 12% once green"],
                 ["Analyst", f"{sum(s.get('vetted', 0) for s in scans)} scored", f"{sc['passed']}/{sc['vetted']} passed last pass", "UNKNOWN = fail"],
                 ["Radar", "pre-trending", "holders +150/10m: UNKNOWN", "needs 10 min of snapshots"],
                 ["CTO Watch", f"{sum(1 for c in C if 'ds_cto' in c['feeds'])} CTOs read", "dev sold 90%+: UNKNOWN", "no dev history in public data"]],
        "messages": {"morning": recaps[-1]["morning"] if recaps else messages.morning(L), "recap": recaps[-1]["text"] if recaps else messages.recap(L),
                     "sells": [messages.sell_alert(t) for t in sells[-6:]][::-1], "lock": messages.lock_line(L),
                     "setup": (S or {}).get("setup")},
        "chat": chat[::-1], "beats": beats,
        "oink": {"cards": cards, "tabs": tabs, "hard_counts": hard_counts, "log": log, "scanned": sc["universe"], "feeds": sc["feeds"],
                 "wl": wl, "hold": (pos[0]["pct"] if pos else None)},
        "table": table, "check_names": [v["check"] for v in C[0]["vet"]] if C else [], "signal_names": [s["check"] for s in C[0].get("signal", [])] if C else [],
        "ntfy": {"topic": nt.get("topic"), "enabled": nt.get("enabled", False)},
    }


if __name__ == "__main__":
    d = build()
    out = os.path.join(store.HERE, "page_data_min.json")
    json.dump(d, open(out, "w"), separators=(",", ":"))
    with open(os.path.join(store.HERE, "page_data_lines.txt"), "w") as f:  # one key per line, for pasting into the Page
        f.write("{\n" + ",\n".join(json.dumps(k) + ":" + json.dumps(v, separators=(",", ":"), ensure_ascii=False) for k, v in d.items()) + "\n}\n")
    print(out, os.path.getsize(out), "bytes · balance", d["balance"], "· fills", d["recap"]["fills"])
