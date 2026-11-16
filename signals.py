"""Entry signals per mode, incl. CTO watch and pre-trending. UNKNOWN never triggers a buy."""
import time
import config

PASS, FAIL, UNK = "PASS", "FAIL", "UNKNOWN"


def momentum(row):
    c = [("buys > sells (5m)", row["buys_m5"] > row["sells_m5"]), ("price up 5m", (row["chg_m5"] or 0) > 0),
         ("price up 1h", (row["chg_h1"] or 0) > 0), ("vol 5m >= $2K", row["vol_m5"] >= config.MIN_VOL_M5_USD)]
    return [{"check": n, "verdict": PASS if v else FAIL} for n, v in c]


def holders_gain(state, mint, window_s):
    h = state["holder_hist"].get(mint) or []
    if len(h) < 2 or h[-1][0] - h[0][0] < window_s:
        return None
    base = next((v for t, v in reversed(h) if h[-1][0] - t >= window_s), None)
    return None if base is None else (h[-1][1] - base, base)


def pre_trending(row, state):
    out = []
    bpm5, bpm60 = row["buys_m5"] / 5.0, row["buys_h1"] / 60.0
    acc = bpm5 / bpm60 if bpm60 > 0 else None
    out.append({"check": "buyers/min 4x+", "verdict": UNK if acc is None else (PASS if acc >= config.PRE_BUYS_ACCEL else FAIL),
                "value": None if acc is None else round(acc, 2)})
    g = holders_gain(state, row["mint"], 600)
    out.append({"check": "holders +150 in 10m", "verdict": UNK if g is None else (PASS if g[0] >= config.PRE_HOLDERS_GAIN_10M else FAIL),
                "value": None if g is None else g[0]})
    return out


def cto_watch(row, vet, state, pp=None):
    out = [{"check": "CTO filed on DexScreener", "verdict": PASS if "ds_cto" in row["feeds"] else FAIL}]
    dp = vet.get("dev_pct")
    out.append({"check": "dev at 0%", "verdict": UNK if dp is None else (PASS if dp == 0 else FAIL), "value": dp})
    init = (pp.creates.get(row["mint"]) or {}).get("initialBuy") if pp else None
    # dev sold 90%+ needs the dev's starting bag; only known for coins whose create event we saw live
    if init and dp is not None:
        out.append({"check": "dev sold 90%+", "verdict": PASS if dp == 0 else UNK, "value": "initial buy seen"})
    else:
        out.append({"check": "dev sold 90%+", "verdict": UNK, "value": "dev history not in public data"})
    g = holders_gain(state, row["mint"], 600)
    out.append({"check": "holders +15% after dump", "verdict": UNK if g is None else (PASS if g[1] and 100 * g[0] / g[1] >= config.CTO_HOLDERS_GAIN_PCT else FAIL),
                "value": None if g is None else g[0]})
    return out


def should_enter(mode, row, vet, state, pp=None):
    if mode in ("goal", "fix-bags", "paycheck", "compound"):
        sig = momentum(row)
    elif mode == "degen":  # new launches only
        age = row.get("age_h")
        sig = momentum(row) + [{"check": "new launch (< 24h)", "verdict": UNK if age is None else (PASS if age < 24 else FAIL), "value": age}]
    elif mode == "pre-trending":
        sig = pre_trending(row, state) + [s for s in momentum(row) if s["check"] == "vol 5m >= $2K"]
    elif mode == "cto-watch":
        sig = cto_watch(row, vet, state, pp)
    else:  # sell-for-me / one-coin pick their own coins
        sig = []
    ok = bool(sig) and vet["passed"] and all(s["verdict"] == PASS for s in sig)
    return ok, sig


def record_holders(state, mint, holders):
    if holders is None:
        return
    h = state["holder_hist"].setdefault(mint, [])
    h.append([time.time(), holders])
    del h[:-60]
