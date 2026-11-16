"""SIZE: answers how many dollars, never whether. Mode size x JEV's size_factor, then the entry guards
(20% cash cap, ticket <= 0.5% of pool, modeled slippage <= 2%, $10 minimum). Hands the order to FILLS."""
import config, risk
from bots.base import Bot


class Size(Bot):
    name, every, job = "SIZE", 3600, "how many dollars · never whether"

    def on(self, m):
        if m["type"] != "pick": return
        P, st = m["payload"], self.book()
        row, R = P["row"], config.MODE_RULES[st["mode"]]
        frac = P.get("size_frac", R["size"]) * P.get("size_factor", 1.0)
        if row["mint"] in st["positions"]:
            return self.say("JEV", "skip", f"{row['symbol']}: already held, no add", task=row["mint"])
        if len(st["positions"]) >= R["max_open"]:
            return self.say("JEV", "skip", f"{row['symbol']}: {R['max_open']}/{R['max_open']} open, no room", task=row["mint"])
        usd, why = risk.ticket(st, row, frac)
        if why:
            return self.say("JEV", "skip", f"{row['symbol']}: {why}", task=row["mint"])
        self.say("FILLS", "order", f"{row['symbol']}: {frac*100:.0f}% of free cash asked → ${usd:,.2f} after guards (liq ${row['liq']/1000:,.1f}K) → FILLS",
                 {"side": "BUY", "row": row, "usd": usd, "reason": P.get("reason", "JEV approved"), "mode": st["mode"], "agent": P.get("agent", "Sniper")},
                 task=row["mint"])
