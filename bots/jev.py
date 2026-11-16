"""JEV: the chief. Takes the one-line setup (chief.parse), starts the seats, judges, delegates, approves or vetoes.

In @Hrundel75's desk Jev is TypeSafe's decision model: it never writes a word, it returns typed answers
(noul = yes/no probability, score, choice) and code acts on the number. We have no TypeSafe key (it needs
an account), so JEV here answers the same typed questions with fixed local rules over the evidence the seats
hand it. The numbers are rule outputs, NOT calibrated probabilities, and they are labelled that way.
JEV's lines are templates filled from the ledger, so nothing on the desk is model prose."""
import math, os, subprocess, sys, time
import config, market, messages, risk, signals, store
from bots import bus, questions as Q
from bots.base import Bot
from bots.scan import Scan
from bots.vet import Vet, _PP
from bots.social import Social
from bots.size import Size
from bots.fills import Fills
from bots.risk_bot import Risk
from bots.piggy import Piggy

SEATS = [Scan, Vet, Social, Size, Fills, Risk, Piggy]


def judge(row, mode, book, quote=None):
    """Ask the question sets for one VET survivor (market + solana + social, as in his questions.py), apply his SOFT
    thresholds (first failure wins, missing = fail), then the mode's entry signal (UNKNOWN = fail).
    The ticket is the one SIZE will send (risk.ticket: 20% cash cap, 0.5% of pool, slippage cap); a SIZE refusal is the kill.
    Last, only for a coin that passed everything else: the sell simulation (sell_route_ok, one Jupiter quote)."""
    st = {"holder_hist": {row["mint"]: row.get("holder_hist") or []}}
    ok, sig = signals.should_enter(mode, row, {"passed": row["passed"], "dev_pct": row.get("dev_pct")}, st,
                                   _PP({row["mint"]: row["create"]} if row.get("create") else {}))
    soc = Q.social(row)
    factor = 1.0 if "account_is_the_project" in soc else Q.NO_SOCIAL_CUT        # same factor decide() hands SIZE
    ticket, refused = risk.ticket(book, row, risk.rules(mode)["size"] * factor)
    row["ticket_usd"], row["size_why"] = ticket, refused
    A = {**Q.market(row, ticket), **Q.solana(row), **soc, **Q.about_me(row)}
    kill = ("size_refused" if refused else None) or Q.soft_kill(A) or (None if ok else "signal")
    if kill is None and row["mint"] not in book["positions"]:
        A.update(Q.sell_route(row, ticket, quote))
        kill = Q.soft_kill(A)
    return kill is None, A, sig, kill


class Jev(Bot):
    name, every, job = "JEV", config.JEV_EVERY_S, "the chief · judges, delegates, approves or vetoes"

    def __init__(self, sid, cursor=0):
        super().__init__(sid, cursor)
        self.halted, self.judged, self.approved, self.vetoed = False, 0, 0, 0
        self.last_loss_ts = 0.0

    def vetoes(self, book):
        v = []
        if self.halted: v.append("desk is off")
        if book["mode"] in ("sell-for-me", "one-coin"): v.append(f"mode {book['mode']} picks its own coins")
        cd = config.JEV_LOSS_COOLDOWN_MIN * 60 - (time.time() - self.last_loss_ts)
        if config.JEV_LOSS_COOLDOWN_MIN and cd > 0: v.append(f"cooldown after a loss, {cd/60:.0f} min left")
        return v

    def on(self, m):
        t, P = m["type"], m["payload"] or {}
        if t == "social":
            self.decide(P)
        elif t == "filled" and P.get("side") == "SELL" and P.get("closed"):
            L = store.read_ledger()
            last = next((x for x in reversed(L) if x["kind"] == "trade" and x["mint"] == P["mint"] and x.get("closed")), None)
            if last and (last.get("pos_pnl_usd") or 0) < 0:
                self.last_loss_ts = time.time()
                if config.JEV_LOSS_COOLDOWN_MIN:
                    self.say("*", "veto", f"loss on {last['symbol']} ({last['pos_pnl_usd']:+,.2f}) → no entries for {config.JEV_LOSS_COOLDOWN_MIN} min", task=P["mint"])
        elif t == "goal_hit":
            if P.get("mode") == "goal":
                self.halted = True
                store.log("exit", f"Goal hit · desk off · ${P['equity']:,.2f} PAPER", alert=True)
                self.say("*", "decision", f"goal hit at ${P['equity']:,.2f} → desk off, FILLS sells everything")
            else:
                store.log("chief", f"line to beat ${P['goal']:,.2f} beaten, still running until clock-out", alert=True)
                self.say("*", "decision", f"line ${P['goal']:,.2f} beaten → keep running until clock-out")
        elif t == "pick" and m["frm"] == "You":
            q = market.quotes([P["mint"]]).get(P["mint"])
            if not q: return self.say("*", "veto", f"your pick {P['mint'][:6]}…: no live quote, skipped", task=P["mint"])
            book = self.book()
            self.say("FILLS", "order", f"your pick {q['symbol']} ${min(P['usd'], book['cash']):,.2f} → FILLS, RISK sells it",
                     {"side": "BUY", "row": q, "usd": min(P["usd"], book["cash"]), "reason": "your pick, Exit adopted it",
                      "mode": "sell-for-me", "agent": "You"}, task=P["mint"])

    def decide(self, P):
        book, rows = self.book(), P["rows"]
        mode = book["mode"]
        survivors, kills, bench = [], {}, {}
        for r in rows:
            if not r["passed"]:
                r["enter"] = False; continue                     # VET killed it: no questions asked (his: never judge a stage-2 kill)
            ok, A, sig, kill = judge(r, mode, book)
            r["signal"], r["enter"], r["answers"], r["kill"] = sig, ok, A, kill
            self.judged += 1
            if ok and r["mint"] not in book["positions"]: survivors.append(r)
            elif kill:
                kills[kill] = kills.get(kill, 0) + 1
                sr = A.get("sell_route_ok") or {}
                if kill == "sell_route_ok": store.log("vet", f"{r['symbol']}: sell_route_ok FAIL · {sr.get('why')}")
                if kill != "signal" and not str(sr.get("why", "")).startswith("jupiter down"): bench[r["mint"]] = kill
        asked = [r["answers"]["sell_route_ok"] for r in rows if "sell_route_ok" in (r.get("answers") or {})]
        if asked and all(str(x.get("why", "")).startswith("jupiter down") for x in asked):
            store.log("vet", f"jupiter down: sell simulation unreachable for {len(asked)} coin(s) → sell_route_ok fails (paper, fails closed)", alert=True)
        if bench: self.say("VET", "bench", f"bench {len(bench)} on the failed question: " + ", ".join(sorted(set(bench.values()))), {"bench": bench})
        store.append("scan", mode=mode, feeds=P["feeds"], universe=P["universe"], vetted=len(rows), passed=sum(r["passed"] for r in rows),
                     candidates=[{k: v for k, v in r.items() if k not in ("holder_hist", "create")} for r in rows], sid=self.sid)
        store.log("scan", f"{P['universe']} scanned · {len(rows)} vetted · {sum(r['passed'] for r in rows)} pass hard+soft · {self.judged} asked")
        why_none = ", ".join(f"{k} {n}" for k, n in sorted(kills.items(), key=lambda kv: -kv[1])) or "nothing survived VET"
        if not survivors:
            store.log("vet", f"no entry: {why_none} (missing = fail)")
            return self.say("*", "decision", f"asked {sum(r['passed'] for r in rows)} · 0 survive the soft gates + signal ({why_none}) · no trade is a result, stand down",
                            {"choice": "none", "kills": kills})
        if len(survivors) == 1:                                  # his rule: never run pick on one survivor
            r, pk = survivors[0], {"best": {"choice": survivors[0]["mint"], "confidence": None}, "worth_trading_at_all": None}
        else:
            pk = Q.pick(survivors)
            worth, best = pk["worth_trading_at_all"]["noul"], pk["best"]
            r = next(x for x in survivors if x["mint"] == best["choice"])
            if worth < Q.PICK_MIN_WORTH or best["probabilities"][best["choice"]] < Q.PICK_MIN_CONF:
                return self.say("*", "decision", f"{len(survivors)} survivors · pick {r['symbol']} p {best['probabilities'][best['choice']]:.2f} · worth {worth:.2f}"
                                f" → under the line (worth ≥ {Q.PICK_MIN_WORTH}, p ≥ {Q.PICK_MIN_CONF}) · no trade", {"choice": "none", "pick": pk})
        A = r["answers"]
        v = self.vetoes(book)
        if v:
            self.vetoed += 1
            return self.say("*", "veto", f"{r['symbol']}: passed every question · but VETO: {'; '.join(v)}", {"answers": A}, task=r["mint"])
        self.approved += 1
        factor = 1.0 if "account_is_the_project" in A else Q.NO_SOCIAL_CUT
        p = (pk["best"].get("probabilities") or {}).get(r["mint"])
        order = {"order_id": time.strftime("%Y-%m-%dT%H:%M:%S"), "token": {"ticker": r["symbol"], "address": r["mint"], "chain": "solana"},
                 "size_factor": factor, "confidence": p, "why": A, "model": Q.MODEL}
        self.say("SIZE", "pick", f"pick {r['symbol']} · shape {A['shape']['choice']} (crowd {A['shape']['probabilities']['crowd']:.2f})"
                 f" · concentration {A['concentration_is_exit_risk']['noul']:.2f} · liq fit {A['liquidity_fits_ticket']['noul']:.2f}"
                 f" · spent {A['momentum_already_spent']['noul']:.2f} · looks-like-my-losses {A['looks_like_my_losses']['noul']:.2f} · " + ("official X" if factor == 1 else f"no usable X → {factor:.2f}x")
                 + (f" · choice p {p:.2f} of {len(survivors)}" if p else " · sole survivor, no pick call") + " (rule scores) → SIZE",
                 {"row": r, "size_factor": factor, "answers": A, "order": order, "reason": f"{mode}: JEV approved (every question + signal PASS)"},
                 task=r["mint"])

    def tick(self):
        book = self.book()
        if book["mode"] == "one-coin" and book.get("one_coin"):
            self.one_coin(book)
        b = bus.beats()
        alive = [n for n in ("SCAN", "VET", "SOCIAL", "SIZE", "FILLS", "RISK", "PIGGY") if n in b and b[n]["sid"] == self.sid and time.time() - b[n]["ts"] < 60]
        self.status = "running"
        self.last = f"{len(alive)}/7 seats beating · judged {self.judged} · approved {self.approved} · vetoed {self.vetoed}"

    def one_coin(self, book):
        m = book["one_coin"]; r = market.quotes([m]).get(m)
        if not r: return
        h = self.mem.setdefault("px", []); h.append([time.time(), r["price"]]); del h[:-120]
        px = [p for _, p in h]
        if len(px) < 10: return
        lo, hi = min(px), max(px)
        if m not in book["positions"] and r["price"] <= lo * 1.02 and hi > lo * 1.04:
            self.say("SIZE", "pick", f"one-coin {r['symbol']} at support → SIZE", {"row": r, "size_frac": 1.0, "reason": "one-coin: bought support"}, task=m)
        elif m in book["positions"] and r["price"] >= hi * 0.98 and r["price"] > book["positions"][m]["entry_fill"] * 1.02:
            self.say("FILLS", "order", f"one-coin {r['symbol']} at resistance → sell", {"side": "SELL", "mint": m, "symbol": r["symbol"], "frac": 1.0,
                     "why": "sold into resistance", "agent": "Exit", "quote_row": r}, task=m)


def check_gap(jev, last_tick, now=None):
    """Honest coverage: a wall-clock jump between JEV ticks means the box was paused (VM snapshot/sleep), nobody scanned
    and nobody watched stops. Write it down, and if anything is open tell RISK to re-check right now (no continuity assumed)."""
    now = time.time() if now is None else now
    if now - last_tick > config.GAP_S:
        mins = round((now - last_tick) / 60, 1)
        store.append("gap", sid=jev.sid, from_ts=round(last_tick, 3), to_ts=round(now, 3), minutes=mins)
        n_open = len(store.load_state()["positions"])
        store.log("chief", f"box was paused {mins:.0f} min (no scanning, no stops watched)" + (f" · {n_open} open → RISK re-checks now" if n_open else ""), alert=bool(n_open))
        jev.say("*", "gap", f"box was paused {mins:.0f} min · {n_open} open", {"from_ts": last_tick, "to_ts": now, "minutes": mins, "open": n_open})
    return now


# ---------------- the shift: JEV runs the session and owns every seat's lifetime ----------------
def spawn_seat(name, sid, cursor):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log = open(os.path.join(here, f"session-{sid}-{name.lower()}.log"), "a")
    return subprocess.Popen([sys.executable, "-u", "-m", "bots.run", name, sid, str(cursor), str(os.getpid())],
                            cwd=here, stdout=log, stderr=log, start_new_session=True)


def supervise(sid, stopflag, inline=None, tick=None):
    import desk  # session helpers (migrate / end_session) stay in desk.py
    inline = config.BOTS_INLINE if inline is None else inline
    tick = config.JEV_EVERY_S if tick is None else tick
    state = desk.migrate(store.load_state()); S = state["session"]
    assert S and S["sid"] == sid, "no such session"
    if os.path.exists(stopflag): os.remove(stopflag)
    S["pid"] = os.getpid(); store.save_state(state)
    cursor = bus.last_id()
    jev = Jev(sid, cursor)
    line = (f"Night {S['night']} · {S['kind']} · mode {state['mode']} · paper equity ${S['start_equity']:,.2f} · ends "
            f"{time.strftime('%H:%M', time.localtime(S['end_ts']))} · PAPER, no wallets")
    store.log("chief", line)
    jev.say("*", "session_start", "JEV · " + line + " · seats: " + ", ".join(c.name for c in SEATS),
            {"setup": (state.get("session") or {}).get("setup"), "mode": state["mode"], "end_ts": S["end_ts"]})
    seats, procs, restarts = [], {}, {}
    if inline:
        seats = [c(sid, cursor) for c in SEATS]
    else:
        procs = {c.name: spawn_seat(c.name, sid, cursor) for c in SEATS}
    why = "end time"
    last_tick = time.time()
    try:
        while time.time() < S["end_ts"]:
            last_tick = check_gap(jev, last_tick)
            if jev.halted: why = "goal"; break
            if os.path.exists(stopflag):
                why = "stop (" + open(stopflag).read().strip() + ")"; break
            for b in seats: b.step()
            jev.step()
            for n, p in list(procs.items()):
                if p.poll() is not None:
                    restarts[n] = restarts.get(n, 0) + 1
                    if restarts[n] > 3:
                        why = f"{n} keeps dying"; raise RuntimeError(why)
                    jev.say("*", "note", f"{n} exited (code {p.returncode}) → restart {restarts[n]}/3")
                    procs[n] = spawn_seat(n, sid, bus.last_id())
            time.sleep(tick)
    except BaseException as e:  # crash / kill / Ctrl-C: still flatten before exiting
        if not why.endswith("dying"): why = f"crash: {type(e).__name__}"
        store.log("chief", f"session crashed ({type(e).__name__}: {str(e)[:80]}), flattening")
    finally:
        wind_down(jev, seats, procs, why)
        state = desk.migrate(store.load_state())
        state["halted"] = jev.halted
        desk.end_session(state, why)
        L = store.read_ledger(); rc = next((x for x in reversed(L) if x["kind"] == "recap"), None)
        if rc:
            jev.say("*", "recap", "JEV · " + rc["text"].replace("\n", " · "))
            jev.say("*", "morning", messages.jev_morning(L, sid, jev))
        jev.status = "off"; jev.last = f"session over ({why})"; bus.beat("JEV", sid, "off", jev.last, jev.n)


def wind_down(jev, seats, procs, why):
    """Flatten through FILLS, let PIGGY say the vault line, then shut every seat and make sure it exited."""
    def pump(sec, until=None):
        end = time.time() + sec
        while time.time() < end:
            for b in seats: b.step()
            got = [m for m in bus.inbox("JEV", jev.cursor) if until and m["type"] == until]
            if got: return got[0]
            if not seats: time.sleep(0.5)
        return None
    try:
        fills_alive = bool(seats) or (procs.get("FILLS") and procs["FILLS"].poll() is None)
        flat = None
        if fills_alive:
            jev.say("FILLS", "flatten", f"session end ({why}) → FILLS: flatten everything", {"why": f"session end ({why}): flatten, no session watching"})
            flat = pump(60 if procs else 5, until="flat")
        jev.say("*", "session_end", f"session end ({why}) · {'FILLS flat' if flat else 'FILLS did not answer, JEV flattens after the seats stop'}")
        pump(3 if procs else 0.01)
        jev.say("*", "shutdown", "all seats off")
        pump(0.01)
    except BaseException as e:  # noqa
        store.log("chief", f"wind-down error {type(e).__name__}, killing seats")
    for n, p in procs.items():
        try:
            p.wait(timeout=15)
        except Exception:  # noqa
            p.kill(); p.wait(timeout=5); jev.say("*", "note", f"{n} did not exit in 15 s, killed")
            bus.beat(n, jev.sid, "off", "killed at session end", 0)
    for b in seats: b.done = True
