"""SCANNER / RADAR: builds the candidate universe from public feeds, pulls DexScreener pair data."""
import time
import sources, store


def universe(pp=None):
    feeds, mints = {}, {}
    for name, path in [("ds_profiles", "/token-profiles/latest/v1"), ("ds_boosts_latest", "/token-boosts/latest/v1"),
                       ("ds_boosts_top", "/token-boosts/top/v1"), ("ds_cto", "/community-takeovers/latest/v1")]:
        try:
            rows = sources.ds_list(path)
            feeds[name] = len(rows)
            for r in rows:
                mints.setdefault(r["tokenAddress"], set()).add(name)
        except Exception as e:  # noqa
            feeds[name] = f"error: {str(e)[:60]}"
    for q in ("pumpswap", "pumpfun", "raydium solana"):
        try:
            prs = [x for x in sources.get(sources.DS + "/latest/dex/search?q=" + q).get("pairs") or [] if x.get("chainId") == "solana"]
            feeds["ds_search_" + q.split()[0]] = len(prs)
            for x in prs:
                mints.setdefault(x["baseToken"]["address"], set()).add("ds_search")
        except Exception as e:  # noqa
            feeds["ds_search_" + q.split()[0]] = f"error: {str(e)[:60]}"
    for name in ("trending", "recent", "new_tokens"):
        try:
            rows = sources.get("https://api.rugcheck.xyz/v1/stats/" + name) or []
            feeds["rugcheck_" + name] = len(rows)
            for r in rows:
                if r.get("mint"):
                    mints.setdefault(r["mint"], set()).add("rc_" + name)
        except Exception as e:  # noqa
            feeds["rugcheck_" + name] = f"error: {str(e)[:60]}"
    ok, data = sources.pumpfun_latest()
    feeds["pumpfun_frontend_api"] = (1 if isinstance(data, dict) else len(data)) if ok else f"blocked: {data}"
    if ok:
        for c in ([data] if isinstance(data, dict) else data):
            if c.get("mint"):
                mints.setdefault(c["mint"], set()).add("pumpfun")
    if pp is not None:
        cut = time.time() - 3 * 3600
        mig = [m for t, m in pp.migrations if t >= cut]
        feeds["pumpportal_migrations_3h"] = len(mig) if pp.ok or mig else f"down: {pp.err}"
        for m in mig:
            mints.setdefault(m, set()).add("pump_graduated")
    return mints, feeds


def scan(pp=None):
    mints, feeds = universe(pp)
    pairs = sources.ds_pairs(list(mints))
    rows = []
    for m, p in pairs.items():
        tx = p.get("txns") or {}
        rows.append({
            "mint": m, "symbol": p["baseToken"].get("symbol"), "name": p["baseToken"].get("name"),
            "dex": p.get("dexId"), "pair": p.get("pairAddress"), "url": p.get("url"),
            "price": float(p.get("priceUsd") or 0), "liq": (p.get("liquidity") or {}).get("usd") or 0,
            "mcap": p.get("marketCap") or p.get("fdv") or 0,
            "vol_m5": (p.get("volume") or {}).get("m5") or 0, "vol_h1": (p.get("volume") or {}).get("h1") or 0,
            "buys_m5": (tx.get("m5") or {}).get("buys", 0), "sells_m5": (tx.get("m5") or {}).get("sells", 0),
            "buys_h1": (tx.get("h1") or {}).get("buys", 0), "sells_h1": (tx.get("h1") or {}).get("sells", 0),
            "chg_m5": (p.get("priceChange") or {}).get("m5"), "chg_h1": (p.get("priceChange") or {}).get("h1"),
            "age_h": round((time.time() * 1000 - (p.get("pairCreatedAt") or 0)) / 3.6e6, 1) if p.get("pairCreatedAt") else None,
            "socials": bool((p.get("info") or {}).get("socials") or (p.get("info") or {}).get("websites")),
            "feeds": sorted(mints[m]),
        })
    rows.sort(key=lambda r: -r["liq"])
    store.log("scanner", f"universe {len(mints)} mints, {len(rows)} with Solana pairs, "
              f"{sum(r['liq'] >= 20000 for r in rows)} with liq>=$20K", feeds=feeds)
    return rows, feeds
