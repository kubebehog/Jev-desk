"""JEV's question sets, copied in shape from @savipww's Megabrain (Jev) guide (questions.py / thresholds.py,
https://x.com/i/status/2102720919185617314, linked from @Hrundel75's posts).

There, each question is sent to TypeSafe's System One ("jev-latest") and comes back typed:
  noul = probability 0..1, score = number on a scale, choice = one label + probabilities.
We have no TypeSafe key, so every answer below is a FIXED LOCAL RULE over the evidence the seats collected.
The numbers are rule outputs, not calibrated probabilities. model = "local-rules-1" so nobody mistakes them.
Missing data stays missing (None) and fails the gate: "NEVER let null mean fine"."""
import math
import config

MODEL = "local-rules-1 (not TypeSafe Jev: no key)"

# thresholds.py, his numbers verbatim where the question exists here
SOFT = {
    "concentration_is_exit_risk": ("max", 0.55),
    "momentum_already_spent":     ("max", 0.60),
    "liquidity_fits_ticket":      ("min", 0.60),
    "account_is_the_project":     ("min", 0.70),
    "dev_still_loaded":           ("max", 0.55),
    "looks_like_my_losses":       ("max", 0.80),   # @Hrundel75 "anti-you": "Above 0.80, the trade is banned. No exceptions."
    "sell_route_ok":              ("min", 1.00),   # HARD, asked last: Jupiter quotes our ticket's SELL back to SOL, impact <= 5% (honeypot check)
}
SHAPE_MIN_CROWD = 0.55
PICK_MIN_WORTH = 0.60
PICK_MIN_CONF = 0.55
NO_SOCIAL_CUT = 0.60          # no usable X handle: trade smaller, do not skip


def clamp(x): return round(min(1.0, max(0.0, x)), 2)


def noul(v): return {"type": "noul", "noul": v}


def chk(row, name):
    return next((c for c in row.get("vet") or [] if c["check"].startswith(name)), {})


def market(row, ticket_usd):
    """MARKET set: shape (choice), liquidity_fits_ticket (noul), momentum_already_spent (noul)."""
    b5, s5, b1, s1 = (row.get(k) or 0 for k in ("buys_m5", "sells_m5", "buys_h1", "sells_h1"))
    hh = row.get("holder_hist") or []
    hold_g = (hh[-1][1] / hh[0][1] - 1) * 100 if len(hh) >= 2 and hh[0][1] else None
    px_g = row.get("chg_h1") or 0
    vm5, vh1 = row.get("vol_m5") or 0, row.get("vol_h1") or 0
    p = {"crowd": 0.1, "one_buyer": 0.1, "fading": 0.1, "too_early": 0.1}
    if (row.get("age_h") or 0) * 60 < 20 or b1 + s1 < 30: p["too_early"] += 0.6
    if s5 > b5 and s1 > b1: p["fading"] += 0.6
    elif vh1 and vm5 * 12 < 0.2 * vh1: p["fading"] += 0.4
    if b5 > s5 and b1 > s1: p["crowd"] += 0.4 + (0.2 if hold_g is None or hold_g >= px_g else 0)
    if px_g > 20 and hold_g is not None and hold_g < px_g / 4: p["one_buyer"] += 0.5
    z = sum(p.values()); p = {k: round(v / z, 2) for k, v in p.items()}
    impact = 100 * ticket_usd / max(row.get("liq") or 1, 1)          # % of the pool
    return {"shape": {"type": "choice", "choice": max(p, key=p.get), "probabilities": p},
            "liquidity_fits_ticket": noul(clamp(1 - max(0.0, impact - 1) / 3)),          # 1.0 up to 1% of pool, 0 at 4%
            "momentum_already_spent": noul(clamp(px_g / 200 + (0.3 if vm5 * 12 < vh1 * 0.5 else 0)))}


def solana(row):
    """CHAIN_SOLANA set: authority_risk (choice), concentration_is_exit_risk (noul), dev_still_loaded (noul)."""
    ma = chk(row, "mint authority").get("verdict")
    tw, t10 = chk(row, "top wallet").get("value"), chk(row, "top-10").get("value")
    conc = None if tw is None and t10 is None else clamp(0.55 * max((tw or 0) / 5.0, (t10 or 0) / 60.0))  # his HARD lines (5% / 60%) map to his 0.55
    dev = row.get("dev_pct")
    return {"authority_risk": {"type": "choice", "choice": {"PASS": "renounced", "FAIL": "mint_open"}.get(ma, "unknown")},
            "concentration_is_exit_risk": noul(conc),
            "dev_still_loaded": noul(None if dev is None else clamp(0.55 * dev / 5.0))}


def social(row):
    """SOCIAL set. Only account_is_the_project can be answered from public data (the handle the project itself
    published on its DexScreener profile). audience_is_real / recycled_account / effort need the X account read,
    which the bot processes don't do: those are 'not asked', exactly like a question not in a chain's set."""
    s = row.get("social") or {}
    if not s.get("x_handle"): return {}                  # no usable X account → NO_SOCIAL_CUT, not a skip
    return {"account_is_the_project": noul(0.85 if s.get("paid_profile") or s.get("cto") else 0.75)}


def about_me(row):
    """@Hrundel75's 'About me' question (core article 2103764774127317363): does this look like a setup I lost on?
    His profile: buys after 3 green candles, buys what the chat screams about. Our desk's own losers were bought after
    +18..+204% in an hour. Rule: 1h run above 10% scales to 1.0 at +50%; +0.3 if the last three 5m candles are green;
    +0.1 with active paid boosts (the 'chat screaming' proxy). The other two 'about me' questions are code, not answers:
    30-min cooldown after a loss (JEV veto) and the fixed slice in SIZE (COLD: same size after a win or a loss)."""
    s = max(0.0, ((row.get("chg_h1") or 0) - 10) / 40)
    c = row.get("candles") or []
    if len(c) >= 3 and all(x[4] > x[1] for x in c[-3:]): s += 0.3
    if ((row.get("social") or {}).get("boosts") or 0) > 0: s += 0.1
    return {"looks_like_my_losses": noul(clamp(s))}


def jup_quote(mint, amount):
    """Jupiter public quote for SELLING `amount` base units of `mint` into SOL. Returns (json, None) or (None, error).
    Read-only market data: a quote is not an order, nothing is signed or sent."""
    import requests, sources
    try:
        r = sources.S.get(config.JUP_QUOTE_URL, params={"inputMint": mint, "outputMint": config.SOL_MINT, "amount": int(amount),
                                                        "slippageBps": config.SELL_SLIPPAGE_BPS}, timeout=10)
    except requests.RequestException as e:
        return None, f"jupiter down: {type(e).__name__}"
    if r.status_code >= 500 or r.status_code == 429:
        return None, f"jupiter down: HTTP {r.status_code}"
    try:
        j = r.json()
    except ValueError:
        return None, f"jupiter down: HTTP {r.status_code}, not json"
    if r.status_code != 200 or "error" in j:
        return None, f"no route: {j.get('errorCode') or j.get('error') or r.status_code}"
    return j, None


def sell_decision(j, err=None):
    """Pure decision over a Jupiter quote dict. -> (noul 1.0 pass / 0.0 fail / None missing, priceImpactPct, why)."""
    if err: return (None if err.startswith("jupiter down") else 0.0), None, err
    if not j or not j.get("routePlan") or int(j.get("outAmount") or 0) <= 0: return 0.0, None, "no route back to SOL"
    try:
        imp = float(j["priceImpactPct"])
    except (KeyError, TypeError, ValueError):
        return None, None, "no priceImpactPct (missing = fail)"
    if imp > config.SELL_MAX_IMPACT: return 0.0, imp, f"sell impact {imp*100:.1f}% > {config.SELL_MAX_IMPACT*100:.0f}%"
    return 1.0, imp, f"sells back to SOL · impact {imp*100:.2f}%"


def sell_route(row, ticket_usd, quote=None):
    """The sell-simulation gate: quote a SELL of the tokens our paper ticket would buy. Missing data = fail."""
    quote = quote or jup_quote
    px, dec = row.get("price") or 0, row.get("decimals")
    if px <= 0 or ticket_usd <= 0:
        return {"sell_route_ok": {"type": "noul", "noul": None, "why": "no price/ticket (missing = fail)"}}
    amount = int(ticket_usd / px * 10 ** (config.SELL_FALLBACK_DECIMALS if dec is None else dec))
    if amount <= 0:
        return {"sell_route_ok": {"type": "noul", "noul": None, "why": "amount rounds to 0"}}
    j, err = quote(row["mint"], amount)
    v, imp, why = sell_decision(j, err)
    if dec is None: why += f" (decimals unknown, assumed {config.SELL_FALLBACK_DECIMALS})"
    return {"sell_route_ok": {"type": "noul", "noul": v, "impact": imp, "amount": amount, "why": why}}


def soft_kill(ans):
    """His soft_kill(): first failure wins. None = missing = fail (his rule: missing data is not neutral)."""
    for name, (d, lim) in SOFT.items():
        if name not in ans: continue
        v = ans[name].get("noul")
        if v is None: return name
        if (d == "max" and v > lim) or (d == "min" and v < lim): return name
    if ans.get("authority_risk", {}).get("choice") != "renounced": return "authority_open"
    sh = ans.get("shape")
    if sh:
        if sh["choice"] in ("fading", "one_buyer"): return "shape"
        if sh["probabilities"]["crowd"] < SHAPE_MIN_CROWD: return "shape_weak"
    return None


def summary(row, ans):
    """Two lines per candidate, built from answers already given (his pick.summary)."""
    return (f"crowd {ans['shape']['probabilities']['crowd']:.2f}, concentration {ans['concentration_is_exit_risk']['noul']:.2f}, "
            f"liq fit {ans['liquidity_fits_ticket']['noul']:.2f}, spent {ans['momentum_already_spent']['noul']:.2f}, "
            + ("official account" if "account_is_the_project" in ans else "no usable X account"))


def pick(survivors):
    """PICK set: best (choice over the survivors) + worth_trading_at_all (noul). Only called with 2+ survivors
    (his rule: NEVER run pick on one survivor)."""
    q = {}
    for r in survivors:
        a = r["answers"]
        q[r["mint"]] = (a["shape"]["probabilities"]["crowd"] + a["liquidity_fits_ticket"]["noul"] + (1 - a["momentum_already_spent"]["noul"])
                        + (1 - a["concentration_is_exit_risk"]["noul"]) + (0.3 if "account_is_the_project" in a else 0)) / 4.3
    z = sum(math.exp(6 * v) for v in q.values())
    probs = {m: round(math.exp(6 * v) / z, 3) for m, v in q.items()}
    best = max(probs, key=probs.get)
    n = len(probs); conf = round((probs[best] - 1 / n) / (1 - 1 / n), 2) if n > 1 else 1.0
    return {"best": {"type": "choice", "choice": best, "probabilities": probs, "confidence": max(conf, round(q[best], 2))},
            "worth_trading_at_all": noul(clamp(max(q.values())))}
