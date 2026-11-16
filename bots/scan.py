"""SCAN: finds candidates. Cannot judge quality at all. Public feeds only (DexScreener profiles/boosts/CTO/search,
rugcheck stats, PumpPortal graduations). Hands a shortlist to VET."""
import config, scanner, sources
from bots.base import Bot


class Scan(Bot):
    name, every, job = "SCAN", config.SCAN_EVERY_S, "finds candidates · cannot judge quality"

    def __init__(self, sid, cursor=0, pp=True):
        super().__init__(sid, cursor)
        self.pp = sources.PumpPortal() if pp and sources.PumpPortal else None

    def tick(self):
        rows, feeds = scanner.scan(self.pp)
        st = self.book()
        picks = set(st.get("picks") or []) | ({st["one_coin"]} if st.get("one_coin") else set())
        pool = [r for r in rows if r["mint"] in picks or "ds_cto" in r["feeds"]] + \
            sorted([r for r in rows if r["liq"] >= config.MIN_LIQ_USD], key=lambda r: -(r["vol_h1"] or 0))
        seen, short = set(), []
        for r in pool:
            if r["mint"] in seen or len(short) >= config.VET_LIMIT: continue
            seen.add(r["mint"])
            r["create"] = (self.pp.creates.get(r["mint"]) if self.pp else None)
            short.append(r)
        self.status = "scanning"
        self.say("VET", "candidates", f"{len(rows)} scanned · {len(short)} with liq ≥ ${config.MIN_LIQ_USD/1000:.0f}K or CTO → VET",
                 {"universe": len(rows), "feeds": feeds, "rows": short})
