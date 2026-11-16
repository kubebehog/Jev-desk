"""Live public quotes (DexScreener) shared by every seat. PAPER: read-only market data."""
import sources


def quotes(mints):
    if not mints: return {}
    return {m: {"mint": m, "symbol": p["baseToken"].get("symbol"), "price": float(p.get("priceUsd") or 0), "liq": (p.get("liquidity") or {}).get("usd") or 0,
                "vol_h1": (p.get("volume") or {}).get("h1") or 0, "vol_h6": (p.get("volume") or {}).get("h6"), "vol_h24": (p.get("volume") or {}).get("h24"), "mcap": p.get("marketCap") or p.get("fdv"), "url": p.get("url"), "pair": p.get("pairAddress"),
                "chg_h1": (p.get("priceChange") or {}).get("h1"), "ts": __import__("time").time()}
            for m, p in sources.ds_pairs(list(mints)).items()}
