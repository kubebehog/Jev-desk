"""FILLS: executes, never reconsiders. The only seat that writes the paper book (state.json).
Every fill re-checks the quote right before it (7 Gates #6/#7): older than ORDER_MAX_AGE_S -> re-quote;
a buy whose fresh quote ran >MAX_CHASE_PCT above the signal price dies. PAPER: no wallet code exists."""
import time
import config, executor, market, risk, store
from bots.base import Bot


class Fills(Bot):
    name, every, job = "FILLS", config.FILLS_EVERY_S, "executes · never reconsiders · only writer of the book"

    def __init__(self, sid, cursor=0):
        super().__init__(sid, cursor)
        self.st = store.load_state()

    def save(self):
        store.save_state(self.st)

    def fresh(self, mint, row):
        if row and time.time() - (row.get("ts") or 0) <= config.ORDER_MAX_AGE_S and row.get("price", 0) > 0:
            return row
        q = market.quotes([mint]).get(mint)
        return q if q and q["price"] > 0 else None

    def on(self, m):
        P, t = m["payload"] or {}, m["type"]
        if t == "order" and P.get("side") == "BUY":
            row = P["row"]; q = self.fresh(row["mint"], row)
            if not q:
                return self.say("JEV", "rejected", f"{row['symbol']}: no live quote at fill time → no data, no trade", task=row["mint"])
            chase = (q["price"] / row["price"] - 1) * 100 if row.get("price") else 0
            if chase > config.MAX_CHASE_PCT:
                return self.say("JEV", "rejected", f"{row['symbol']}: quote ran {chase:+.1f}% since the signal (> {config.MAX_CHASE_PCT:.0f}%) → order dies", task=row["mint"])
            if P.get("mode") == "sell-for-me":
                self.st["mode"] = "sell-for-me"; self.st["picks"] = sorted(set(self.st.get("picks") or []) | {row["mint"]})
            pos = executor.paper_buy(self.st, {**row, **{k: q[k] for k in ("price", "liq", "mcap") if q.get(k) is not None}},
                                     P["usd"], P["reason"], P["mode"], agent=P.get("agent", "Sniper"))
            self.save()
            if pos:
                self.say("*", "filled", f"{P.get('agent', 'Sniper')} · Bought {row['symbol']} ${P['usd']:,.2f} · fill {pos['entry_fill']:.8g} · PAPER",
                         {"side": "BUY", "mint": row["mint"], "usd": P["usd"]}, task=row["mint"])
        elif t == "order" and P.get("side") == "SELL":
            mint = P["mint"]
            if mint not in self.st["positions"]:
                return self.say(m["frm"], "rejected", f"{P.get('symbol', mint[:6])}: already flat", task=mint)
            q = self.fresh(mint, P.get("quote_row"))
            if not q:
                return self.say(m["frm"], "rejected", f"{P.get('symbol')}: no live quote, holding", task=mint)
            sym = self.st["positions"][mint]["symbol"]
            pnl = executor.paper_sell(self.st, mint, P["frac"], q["price"], q["liq"], P["why"], agent=P.get("agent", "Exit"), mcap=q.get("mcap"))
            self.save()
            self.say("*", "filled", f"{P.get('agent', 'Exit')} · Sold {sym}{'' if P['frac'] >= 0.999 else f' {P['frac']*100:.0f}%'} · {pnl:+,.2f} · {P['why']} · PAPER",
                     {"side": "SELL", "mint": mint, "pnl": pnl, "closed": mint not in self.st["positions"]}, task=mint)
        elif t == "lock":
            usd = min(P["usd"], self.st["cash"])
            self.st["vault"] = round(self.st.get("vault", 0) + usd, 2); self.st["cash"] -= usd
            store.log("piggy", P.get("why", f"${usd:.2f} locked in the vault"), alert=True)
            self.save()
            self.say("*", "locked", f"vault +${usd:,.2f} → ${self.st['vault']:,.2f} · only house money rides · PAPER")
        elif t == "flatten":
            left = self.flatten(P.get("why", "session end: flatten"))
            self.say("JEV", "flat", f"flattened · {len(left)} left open" + (" (no quote)" if left else ""), {"left": left})

    def flatten(self, why):
        if self.st["positions"]:
            q = market.quotes(set(self.st["positions"]))
            for mint in list(self.st["positions"]):
                if mint in q and q[mint]["price"] > 0:
                    executor.paper_sell(self.st, mint, 1.0, q[mint]["price"], q[mint]["liq"], why, agent="Exit", mcap=q[mint].get("mcap"))
            self.save()
        return list(self.st["positions"])

    def tick(self):
        q = market.quotes(set(self.st["positions"]))
        eq = risk.equity(self.st, q)
        store.append("equity", equity=eq, cash=round(self.st["cash"], 4), vault=self.st.get("vault", 0), open=len(self.st["positions"]),
                     sid=self.sid, positions={m: {"symbol": p["symbol"], "qty": p["qty"], "quote": (q.get(m) or {}).get("price"),
                                                   "mcap": (q.get(m) or {}).get("mcap"), "mode": p["mode"]} for m, p in self.st["positions"].items()})
        self.status = f"{len(self.st['positions'])} open"; self.last = f"book ${eq:,.2f} · cash ${self.st['cash']:,.2f} · PAPER"
