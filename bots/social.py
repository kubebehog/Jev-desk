"""SOCIAL: who's talking. Reads only what public data exposes without an account:
DexScreener project links (X / Telegram / website, set by the project), boosts, CTO filings and paid-profile orders.
No handle = a gap, not a pass. X post reading is NOT done here (that needs the owner's X connector; see BOTS_SPEC.md)."""
import re
import config, sources
from bots.base import Bot

UNAVAILABLE = "X mentions: not read (needs the owner's X connector; bot processes never call it)"


def facts(pair, orders, feeds):
    info = (pair or {}).get("info") or {}
    soc = {s.get("type"): s.get("url") for s in info.get("socials") or []}
    x = soc.get("twitter") or soc.get("x")
    handle = None
    if x:
        mm = re.search(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})(?:[/?]|$)", x)
        handle = mm.group(1) if mm and mm.group(1).lower() not in ("i", "search", "home") else None
    kinds = {o.get("type"): o.get("status") for o in orders or []}
    f = {"x_handle": handle, "x_is_community": bool(x and "/i/communities/" in x), "telegram": bool(soc.get("telegram")),
         "website": bool(info.get("websites")), "boosts": ((pair or {}).get("boosts") or {}).get("active") or 0,
         "cto": "ds_cto" in feeds or kinds.get("communityTakeover") == "approved",
         "paid_profile": kinds.get("tokenProfile") == "approved", "x_mentions": None}
    f["read"] = "ok" if (handle or f["x_is_community"] or f["telegram"] or f["website"]) else "gap"
    return f


class Social(Bot):
    name, every, job = "SOCIAL", 3600, "who's talking · links/boosts/CTO only, no post reading"

    def on(self, m):
        if m["type"] != "vetted": return
        P = m["payload"]; rows = P["rows"]
        self.status = "reading"
        top = sorted(rows, key=lambda v: (-v["passed"], -(v["vol_h1"] or 0)))[:config.SOCIAL_LIMIT]
        pairs = {}
        try:
            pairs = sources.ds_pairs([v["mint"] for v in top])
        except Exception as e:  # noqa
            self.say("JEV", "note", f"DexScreener pairs failed ({str(e)[:40]}): social = gap for this pass")
        for v in top:
            try:
                orders = (sources.get(f"{sources.DS}/orders/v1/solana/{v['mint']}") or {}).get("orders") if v["passed"] else []
            except Exception:  # noqa
                orders = []
            v["social"] = facts(pairs.get(v["mint"]), orders, v.get("feeds") or [])
        for v in rows:
            v.setdefault("social", {"read": "gap", "why": "not in SOCIAL's top " + str(config.SOCIAL_LIMIT)})
        ok = sum(1 for v in top if v["social"]["read"] == "ok")
        gaps = [v["symbol"] for v in top if v["passed"] and v["social"]["read"] == "gap"]
        self.say("JEV", "social", f"{len(top)} read · {ok} with project links · " +
                 (f"gap on {', '.join(gaps[:3])} · " if gaps else "") + "X mentions not read (no connector)", {**P, "rows": rows})
        self.status = "idle"
