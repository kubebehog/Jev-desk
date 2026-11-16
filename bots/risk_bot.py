"""RISK: closes. One rule, no conversation. Re-quotes every open position every RISK_EVERY_S and sends
FILLS a sell when the mode's stop / ladder / trail fires (risk.decide). Keeps peak/tp state in its own memory."""
import time
import config, market, risk
from bots.base import Bot


class Risk(Bot):
    name, every, job = "RISK", config.RISK_EVERY_S, "closes · one rule, no conversation"

    def on(self, m):
        if m["type"] == "gap": self._t = 0     # box was paused: re-quote every open position on this step, don't wait

    def tick(self):
        st = self.book(); pos = st["positions"]
        tr, pend = self.mem.setdefault("track", {}), self.mem.setdefault("pending", {})
        for m in list(tr):
            if m not in pos: tr.pop(m); pend.pop(m, None)
        if not pos:
            self.status, self.last = "idle · flat", "flat · nothing to watch"; return
        q = market.quotes(set(pos)); lines = []
        for m, p in pos.items():
            row = q.get(m)
            if not row or row["price"] <= 0:
                lines.append(f"{p['symbol']} no quote, holding"); continue
            if m in pend and pend[m]["qty"] == p["qty"] and time.time() - pend[m]["ts"] < 20:
                continue  # FILLS hasn't done the last sell yet
            t = tr.setdefault(m, {"peak": p["peak"], "tp_done": p.get("tp_done", 0)})
            acts, notes = risk.decide(p, row, t)
            for n in notes: self.say("*", "note", n, task=m)
            pct = (row["price"] / p["entry_fill"] - 1) * 100
            lines.append(f"{p['symbol']} {pct:+.1f}%")
            for frac, why, agent in acts:
                self.say("FILLS", "order", f"sell {p['symbol']} {frac*100:.0f}% · {why} ({pct:+.1f}% vs entry)",
                         {"side": "SELL", "mint": m, "symbol": p["symbol"], "frac": frac, "why": why, "agent": agent,
                          "quote_row": {**row, "ts": time.time()}}, task=m)
                pend[m] = {"qty": p["qty"], "ts": time.time()}
        self.save_mem()
        R = risk.rules(st["mode"])
        self.status = f"watching {len(pos)}"; self.last = " · ".join(lines) + f" · stop {R['stop']}% trail {R['trail']}%"
