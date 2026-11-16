"""VET: kills most of SCAN's list. Hard checks are gates (UNKNOWN = fail), then the three SOFT numbers.
Keeps its own holder history (for pre-trending / CTO signals) and pulls candles for the chart panel."""
import time
import analyst, config, sources
from bots import bus
from bots.base import Bot


class _PP:  # analyst.vet only needs .creates
    def __init__(self, creates): self.creates = creates


def candles(pair):
    try:
        j = sources.get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair}/ohlcv/minute?aggregate=5&limit=48")
        return [[c[0], c[1], c[2], c[3], c[4], round(c[5])] for c in reversed(j["data"]["attributes"]["ohlcv_list"])]
    except Exception:  # noqa
        return None


# how long a rejection stands, by what fired it (his book.py BENCH_MINUTES, mapped to our check names;
# the three marked "inferred" have no direct twin in his table)
BENCH_MINUTES = {
    "mint authority revoked": 100_000, "authority_open": 100_000, "top wallet <= 6%": 100_000,   # facts that won't change
    "not bundled (proxy)": 360, "copycat_ticker": 360,                                           # slow (inferred)
    "top-10 holders <= 30%": 90, "dev wallet < 5%": 90, "dev_still_loaded": 90, "concentration_is_exit_risk": 90,
    "LP burned/locked >= 90%": 90, "cluster_risk": 90,                                           # LP/cluster inferred
    "sell_route_ok": 25, "size_refused": 25, "shape": 25, "shape_weak": 25, "momentum_already_spent": 25, "momentum_spent": 25, "liquidity_fits_ticket": 25,
    "liquidity >= $20K": 25, "vol 1h >= $25K": 25, "age >= 20 min": 20,
}
DEFAULT_BENCH, UNKNOWN_BENCH = 45, 10      # an UNKNOWN can be a flaky API: short bench, then ask again


class Vet(Bot):
    name, every, job = "VET", 3600, "kills most of SCAN's list · UNKNOWN = fail"

    def sit(self, mint, reason, unknown=False):
        mins = UNKNOWN_BENCH if unknown else BENCH_MINUTES.get(reason, DEFAULT_BENCH)
        self.mem.setdefault("bench", {})[mint] = [reason, time.time() + mins * 60]

    def on(self, m):
        if m["type"] == "bench":                                # JEV benches on the failed question
            for mint, why in (m["payload"] or {}).get("bench", {}).items(): self.sit(mint, why)
            return self.save_mem()
        if m["type"] != "candidates": return
        if any(x["type"] == "candidates" for x in bus.inbox(self.name, m["id"])):
            return self.say("SCAN", "note", "skipped a stale list, a newer one is waiting")   # never vet old data
        P, vetted, hh = m["payload"], [], self.mem.setdefault("holder_hist", {})
        bench = self.mem.setdefault("bench", {})
        now = time.time()
        rows = [r for r in P["rows"] if not (r["mint"] in bench and bench[r["mint"]][1] > now)]
        benched = len(P["rows"]) - len(rows)
        self.status = "vetting"
        for i, r in enumerate(rows):
            if any(x["type"] == "shutdown" for x in bus.inbox(self.name, self.cursor)):
                self.status = "stopped mid-pass"; return          # session is ending: drop the pass, let step() see shutdown
            self.status = f"vetting {i + 1}/{len(rows)}"; self.last = f"checking {r['symbol']} (rugcheck + RPC)"
            bus.beat(self.name, self.sid, self.status, self.last, self.n)
            try:
                v = analyst.vet(r, _PP({r["mint"]: r["create"]} if r.get("create") else {}))
            except Exception as e:  # noqa
                self.say("JEV", "note", f"{r['symbol']}: vet error {str(e)[:50]} → UNKNOWN = fail", task=r["mint"]); continue
            if v["holders"] is not None:
                h = hh.setdefault(r["mint"], []); h.append([time.time(), v["holders"]]); del h[:-60]
            vetted.append({**r, "vet": v["checks"], "passed": v["passed"], "hard_ok": v["passed"], "holders": v["holders"],
                           "dev_pct": v["dev_pct"], "decimals": v.get("decimals"), "holder_hist": hh.get(r["mint"], [])})
            time.sleep(0.3)
        analyst.soft_scores(vetted)
        for v in sorted(vetted, key=lambda v: (-v["passed"], -(v["vol_h1"] or 0)))[:5]:
            v["candles"] = candles(v["pair"]) if v.get("pair") else None
        kills = {}
        for v in vetted:
            if v["passed"]: continue
            bad = next((c for c in v["vet"] if c["verdict"] != "PASS"), None)
            first = bad["check"] if bad else \
                next((k for k, x in (v.get("soft") or {}).items() if x is None or x > config.SOFT_MAX[k]), "soft")
            kills[first] = kills.get(first, 0) + 1
            self.sit(v["mint"], first, unknown=bool(bad and bad["verdict"] != "FAIL"))
        top = ", ".join(f"{k} {n}" for k, n in sorted(kills.items(), key=lambda kv: -kv[1])[:3])
        n_pass = sum(v["passed"] for v in vetted)
        self.save_mem()
        self.say("SOCIAL", "vetted", f"{len(vetted)} vetted · {n_pass} pass hard+soft · {len(vetted)-n_pass} killed" + (f" ({top})" if top else "")
                 + (f" · {benched} benched, not re-checked" if benched else ""),
                 {**{k: P[k] for k in ("universe", "feeds")}, "rows": vetted, "kills": kills, "benched": benched})
        self.status = "idle"
