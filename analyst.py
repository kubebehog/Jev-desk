"""ANALYST + DEV-WATCH: hard filters. Each check -> PASS / FAIL / UNKNOWN. UNKNOWN counts as FAIL."""
import config, sources

PASS, FAIL, UNK = "PASS", "FAIL", "UNKNOWN"


def chk(name, verdict, value, src):
    return {"check": name, "verdict": verdict, "value": value, "src": src}


def vet(row, pp=None):
    m, checks, rc, decimals = row["mint"], [], None, None
    checks.append(chk("liquidity >= $20K", PASS if row["liq"] >= config.MIN_LIQ_USD else FAIL,
                      round(row["liq"]), "dexscreener"))
    age_min = None if row.get("age_h") is None else row["age_h"] * 60
    checks.append(chk("age >= 20 min", UNK if age_min is None else (PASS if age_min >= config.MIN_AGE_MIN else FAIL),
                      None if age_min is None else round(age_min), "dexscreener pairCreatedAt"))
    checks.append(chk("vol 1h >= $25K", PASS if (row["vol_h1"] or 0) >= config.MIN_VOL_1H else FAIL, round(row["vol_h1"] or 0), "dexscreener"))
    try:
        rc = sources.rugcheck(m)
    except Exception as e:  # noqa
        rc_err = str(e)[:60]
    # mint authority: Solana RPC is authoritative, rugcheck as fallback
    try:
        mi = sources.mint_info(m)
        checks.append(chk("mint authority revoked", PASS if mi.get("mintAuthority") is None else FAIL,
                          mi.get("mintAuthority") or "none", "solana rpc"))
        supply = int(mi["supply"]); decimals = mi.get("decimals")
    except Exception:  # noqa
        supply = int(((rc or {}).get("token") or {}).get("supply") or 0) or None
        decimals = ((rc or {}).get("token") or {}).get("decimals")
        if rc and "token" in rc:
            checks.append(chk("mint authority revoked", PASS if rc["token"].get("mintAuthority") is None else FAIL,
                              rc["token"].get("mintAuthority") or "none", "rugcheck"))
        else:
            checks.append(chk("mint authority revoked", UNK, None, "rpc+rugcheck failed"))
    # dev wallet % (creator from rugcheck, live balance from RPC)
    creator = (rc or {}).get("creator") or ((pp.creates.get(m) or {}).get("dev") if pp else None)
    dev_pct = None
    if creator and supply:
        try:
            dev_pct = 100.0 * sources.owner_balance_raw(creator, m) / supply
            checks.append(chk("dev wallet < 5%", PASS if dev_pct < config.MAX_DEV_PCT else FAIL, round(dev_pct, 3), "rugcheck creator + rpc balance"))
        except Exception:  # noqa
            checks.append(chk("dev wallet < 5%", UNK, None, "rpc balance failed"))
    else:
        checks.append(chk("dev wallet < 5%", UNK, None, "creator not in public data"))
    # top-10 holders, excluding AMM pools / lockers / bonding curve
    if rc and rc.get("topHolders"):
        skip = {mk.get("pubkey") for mk in rc.get("markets") or []}
        skip |= {a for a, k in (rc.get("knownAccounts") or {}).items() if k.get("type") in ("AMM", "LOCKER")}
        hs = [h for h in rc["topHolders"] if h.get("owner") not in skip and h.get("address") not in skip][:10]
        t10 = sum(h.get("pct") or 0 for h in hs)
        top1 = max([h.get("pct") or 0 for h in hs] or [0])
        checks.append(chk("top wallet <= 6%", PASS if top1 <= config.MAX_TOP_WALLET_PCT else FAIL, round(top1, 2), "rugcheck topHolders (pools excluded)"))
        checks.append(chk("top-10 holders <= 30%", PASS if t10 <= config.MAX_TOP10_PCT else FAIL, round(t10, 2), "rugcheck topHolders (pools excluded)"))
    else:
        checks.append(chk("top wallet <= 6%", UNK, None, "no holder list"))
        checks.append(chk("top-10 holders <= 30%", UNK, None, "no holder list"))
    # LP burned / locked
    mk = [x for x in ((rc or {}).get("markets") or []) if (x.get("lp") or {}).get("lpLockedPct") is not None]
    if mk:
        best = max(mk, key=lambda x: (x["lp"].get("quoteUSD") or 0))
        v = best["lp"]["lpLockedPct"]
        checks.append(chk("LP burned/locked >= 90%", PASS if v >= config.MIN_LP_LOCKED_PCT else FAIL, round(v, 1), f"rugcheck {best.get('marketType')}"))
    else:
        checks.append(chk("LP burned/locked >= 90%", UNK, None, "no LP data"))
    # bundled launch: proxy only (rugcheck insider graph). same-slot launch buys are NOT checked here.
    gi = (rc or {}).get("graphInsidersDetected")
    if gi is None:
        checks.append(chk("not bundled (proxy)", UNK, None, "rugcheck insider graph missing"))
    else:
        checks.append(chk("not bundled (proxy)", PASS if gi <= config.MAX_INSIDER_NETWORKS else FAIL, gi, "rugcheck insider graph; same-slot buys unchecked"))
    ok = all(c["verdict"] == PASS for c in checks)
    return {"mint": m, "symbol": row["symbol"], "passed": ok, "checks": checks, "creator": creator, "dev_pct": dev_pct, "decimals": decimals,
            "holders": (rc or {}).get("totalHolders"), "rugged": (rc or {}).get("rugged")}


def norm(sym):
    return "".join(ch for ch in (sym or "").lower() if ch.isalpha())


def soft_scores(vetted):
    """SOFT checks, one number 0..1 each (computed, not asked of a human):
    cluster_risk  = insider wallets / 50 (rugcheck graph), capped at 1
    momentum_spent= 1h price change / 200%, clamped 0..1 (already ran = spent)
    copycat_ticker= 1 if an older/bigger coin in this scan has the same ticker or name"""
    for v in vetted:
        ins = next((c["value"] for c in v["vet"] if c["check"].startswith("not bundled")), None)
        cr = None if ins is None else min(1.0, ins / 50)
        ms = min(1.0, max(0.0, (v.get("chg_h1") or 0) / 200))
        twins = [o for o in vetted if o is not v and (norm(o["symbol"]) == norm(v["symbol"]) or norm(o["name"]) == norm(v["name"]))]
        cc = 1.0 if any((o.get("age_h") or 0) > (v.get("age_h") or 0) or o["liq"] > v["liq"] for o in twins) else 0.0
        v["soft"] = {"cluster_risk": cr, "momentum_spent": round(ms, 2), "copycat_ticker": cc}
        soft_ok = all(val is not None and val <= config.SOFT_MAX[k] for k, val in v["soft"].items())
        v["soft_ok"] = soft_ok
        v["passed"] = v["passed"] and soft_ok
        # the six checks on the OINK scanner panel
        vd = {c["check"]: c["verdict"] for c in v["vet"]}
        vm = (v.get("vol_h1") or 0) / v["mcap"] if v.get("mcap") else None
        v["panel"] = [["liquidity depth", vd.get("liquidity >= $20K", FAIL)],
                      ["holder spread", PASS if vd.get("top-10 holders <= 30%") == PASS and vd.get("top wallet <= 6%") == PASS else (UNK if UNK in (vd.get("top-10 holders <= 30%"), vd.get("top wallet <= 6%")) else FAIL)],
                      ["volume vs mcap", UNK if vm is None else (PASS if vm >= 0.05 else FAIL)],
                      ["fresh wallets", UNK],
                      ["copycat ticker", PASS if cc <= config.SOFT_MAX["copycat_ticker"] else FAIL],
                      ["entry window", PASS if vd.get("age >= 20 min") == PASS and ms <= config.SOFT_MAX["momentum_spent"] else FAIL]]
    return vetted
