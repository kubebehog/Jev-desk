"""Do the public data sources answer from this runner? DexScreener is required; the rest are reported."""
import sys, requests
H = {"User-Agent": "Mozilla/5.0 hrundel-desk-paper/1.0"}
SOL, USDC = "So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
U = {"dexscreener": "https://api.dexscreener.com/token-profiles/latest/v1",
     "rugcheck": f"https://api.rugcheck.xyz/v1/tokens/{SOL}/report",
     "geckoterminal": "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools",
     "jupiter": f"https://lite-api.jup.ag/swap/v1/quote?inputMint={USDC}&outputMint={SOL}&amount=1000000&slippageBps=200",
     "solana-rpc": "https://api.mainnet-beta.solana.com",
     "pump.fun": "https://frontend-api-v3.pump.fun/coins/latest"}
bad = []
for k, u in U.items():
    try:
        r = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"}, headers=H, timeout=15) if k == "solana-rpc" else requests.get(u, headers=H, timeout=15)
        print(f"{k:14s} {r.status_code}"); ok = r.status_code == 200
    except Exception as e:  # noqa
        print(f"{k:14s} error {str(e)[:80]}"); ok = False
    if not ok: bad.append(k)
try:  # PumpPortal = the pump.fun relay the desk's SCAN uses (websocket)
    from websockets.sync.client import connect
    with connect("wss://pumpportal.fun/api/data", open_timeout=10) as ws: ws.send('{"method":"subscribeNewToken"}'); print("pumpportal-ws  ok", ws.recv(timeout=15)[:60])
except Exception as e:  # noqa
    print(f"pumpportal-ws  error {str(e)[:80]}")
sys.exit("dexscreener is down from the runner" if "dexscreener" in bad else 0)
