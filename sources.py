"""Public data only: DexScreener, RugCheck, Solana public RPC, PumpPortal WS (pump.fun relay).
No keys, no wallets, no logins."""
import json, threading, time
import requests

UA = {"User-Agent": "Mozilla/5.0 hrundel-desk-paper/1.0"}
DS = "https://api.dexscreener.com"
RPC = "https://api.mainnet-beta.solana.com"
S = requests.Session(); S.headers.update(UA)


def get(url, timeout=15):
    r = S.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ds_list(path):
    return [x for x in get(DS + path) if x.get("chainId") == "solana"]


def ds_pairs(mints):
    """mint -> best (highest liquidity) Solana pair."""
    out = {}
    mints = list(dict.fromkeys(mints))
    for i in range(0, len(mints), 30):
        for p in get(DS + "/tokens/v1/solana/" + ",".join(mints[i:i + 30])) or []:
            m = p["baseToken"]["address"]
            if m not in mints:
                continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if m not in out or liq > ((out[m].get("liquidity") or {}).get("usd") or 0):
                out[m] = p
    return out


def pumpfun_latest():
    """pump.fun frontend API. Behind Cloudflare from this box; returns (ok, data_or_error)."""
    try:
        r = S.get("https://frontend-api-v3.pump.fun/coins/latest", timeout=10)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        return True, r.json()
    except Exception as e:  # noqa
        return False, str(e)[:80]


_rc_cache = {}


def rugcheck(mint, max_age=300):
    c = _rc_cache.get(mint)
    if c and time.time() - c[0] < max_age:
        return c[1]
    for attempt in range(3):
        r = S.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report", timeout=20)
        if r.status_code == 429:
            time.sleep(3 + 3 * attempt); continue
        r.raise_for_status()
        d = r.json(); _rc_cache[mint] = (time.time(), d); return d
    raise RuntimeError("rugcheck 429")


def rpc(method, params):
    for attempt in range(3):
        r = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
        if r.status_code == 429:
            time.sleep(2 + 2 * attempt); continue
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise RuntimeError(str(j["error"])[:120])
        return j["result"]
    raise RuntimeError("rpc 429")


def mint_info(mint):
    v = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
    return v["data"]["parsed"]["info"]  # mintAuthority, freezeAuthority, supply, decimals


def owner_balance_raw(owner, mint):
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])["value"]
    return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for a in res)


class PumpPortal:
    """Background listener for pump.fun new tokens + migrations (graduations) via PumpPortal public WS."""

    def __init__(self):
        self.migrations, self.creates, self.ok, self.err = [], {}, False, None
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        from websockets.sync.client import connect
        while True:
            try:
                with connect("wss://pumpportal.fun/api/data", open_timeout=15) as ws:
                    ws.send(json.dumps({"method": "subscribeMigration"}))
                    ws.send(json.dumps({"method": "subscribeNewToken"}))
                    self.ok = True
                    for raw in ws:
                        m = json.loads(raw)
                        if m.get("txType") == "migrate":
                            self.migrations.append((time.time(), m["mint"]))
                        elif m.get("txType") == "create":
                            # dev initial buy is known for coins we watched being created
                            self.creates[m["mint"]] = {"ts": time.time(), "dev": m.get("traderPublicKey"),
                                                       "initialBuy": m.get("initialBuy"), "name": m.get("name"),
                                                       "symbol": m.get("symbol")}
                            if len(self.creates) > 20000:
                                self.creates.pop(next(iter(self.creates)))
            except Exception as e:  # noqa
                self.ok, self.err = False, str(e)[:100]
                time.sleep(5)
