"""DESK config. PAPER ONLY. Rules are copied from @Hrundel75's rule blocks (see GAPS.md for the post each comes from)."""
PAPER = True                    # hard-coded; there is no live path in this codebase
START_BALANCE_USD = 1000.0      # paper USD
DEFAULT_GOAL_USD = 2000.0
MAX_SESSION_HOURS = 12          # every session has an end time; nothing runs forever

# HARD (thresholds.py "arithmetic, costs nothing" + dev-watch). UNKNOWN == FAIL.
MIN_LIQ_USD = 20_000            # brief says $20K (his panel shows 15,000; we keep the stricter one)
MIN_AGE_MIN = 20                # min_age_min 20
MIN_VOL_1H = 25_000             # min_vol_1h 25,000
MAX_TOP_WALLET_PCT = 6.0        # max_top_wallet 0.06
MAX_TOP10_PCT = 30.0            # max_top_10 0.30
MAX_DEV_PCT = 5.0               # "dev holds under 5%"
MIN_LP_LOCKED_PCT = 90.0        # "LP is burned"
MAX_INSIDER_NETWORKS = 0        # bundle proxy: rugcheck insider graph must be clean
# SOFT ("one number each", max)
SOFT_MAX = {"cluster_risk": 0.50, "momentum_spent": 0.55, "copycat_ticker": 0.40}
MIN_VOL_M5_USD = 2_000          # momentum entry signal

PRE_BUYS_ACCEL = 4.0
PRE_HOLDERS_GAIN_10M = 150
CTO_HOLDERS_GAIN_PCT = 15.0
CTO_DEV_SOLD_PCT = 90.0

# Per-mode rules, verbatim from his rule blocks.
#  size = fraction of free cash per buy; trail arms once the position is green; ladder = [(gain%, fraction of original)]
MODE_RULES = {
    "goal":         dict(size=0.60, max_open=2, stop=-18, trail=12, ladder=[], auto_stop=True,
                         text="every buy is 60% of free cash · every win rolls into the next buy · max 2 open, trail 12%, stop −18% · at the goal Exit sells everything, then the desk shuts itself off"),
    "paycheck":     dict(size=0.60, max_open=2, stop=-18, trail=12, ladder=[], auto_stop=False,
                         text="the line to beat is the paycheck · every buy is 60% of free cash · max 2 open, trail 12%, stop −18% · no auto-stop, runs until clock-out"),
    "compound":     dict(size=0.60, max_open=2, stop=-18, trail=12, ladder=[], lock_at=2.0,
                         text="every buy is 60% of free cash · when cash hits 2x the start, the start is locked in the vault · only house money rides"),
    "degen":        dict(size=0.24, max_open=3, stop=-6, trail=12, ladder=[], breakeven=True, max_age_h=24,
                         text="new launches only · Risk puts a −6% stop under every buy and moves it to entry once it's green · Banker sells on a 12% trailing stop · max 3 open"),
    "one-coin":     dict(size=1.00, max_open=1, stop=-5, trail=8, ladder=[],
                         text="buy support, sell resistance · all of the balance, one trade at a time · range breaks down, out at −5% · range breaks out, trail 8% instead"),
    "fix-bags":     dict(size=0.60, max_open=2, stop=-18, trail=12, ladder=[],
                         text="dead bag, sell it now · alive bag, keep it with a stop at −18% · dead-bag cash goes to the Compounder (60% of free cash) · max 2 open, trail 12%"),
    "sell-for-me":  dict(size=0.0, max_open=99, stop=-18, trail=15, ladder=[(100.0, 0.25)],
                         text="you pick, Exit sells · Exit sells 25% at x2, the rest on a 15% trail · stop −18% · coins the desk picks: 0"),
    "pre-trending": dict(size=0.40, max_open=2, stop=-18, trail=15, ladder=[], trending_sell=0.50,
                         text="buyers/min up 4x+ · holders +150 in 10 min · dev under 5% · no bundled launches · 40% of free cash · on Trending Exit sells 50% · rest 15% trail, stop −18%"),
    "cto-watch":    dict(size=0.40, max_open=2, stop=-18, trail=15, ladder=[], dev_exit_sell=0.50,
                         text="dev sold 90%+ · dev at 0% · holders +15% after the dump · CTO filed on DexScreener · 40% of free cash · Exit sells 50% back at the dev's exit price · rest 15% trail, stop −18%"),
}
MODES = list(MODE_RULES)

# executor cost model (stated assumption)
FEE_PCT_PER_SIDE = 1.0          # ~0.25% DEX LP fee + ~0.75% trading-frontend/priority cost
BASE_SLIP_PCT = 0.5
MAX_SLIP_PCT = 15.0             # price impact = ticket / (liquidity_usd / 2)

# --- entry guards from RESEARCH.md (paper-tested changes; set ENTRY_GUARDS = False to get the old behavior) ---
# Our ledger: 7 fills paid $99 in modeled slippage+fees (31% of the -$324 loss); tickets were 1.2-2.2% of pool
# liquidity -> 2.8-4.9% entry slippage, so a round trip cost ~8-12% before the coin moved at all.
ENTRY_GUARDS = True
SIZE_CAP = 0.20                 # never more than 20% of free cash per entry (mode rules said 40-60%)
MAX_TICKET_PCT_OF_LIQ = 0.5     # ticket <= 0.5% of pool liquidity -> modeled impact <= 1%
MAX_ENTRY_SLIP_PCT = 2.0        # skip if modeled entry slippage (base + impact) is above this
MIN_TICKET_USD = 10.0           # don't bother below this after the caps
MAX_ENTRY_CHG_H1 = None         # anti-chase (e.g. 100 = skip coins already +100% in 1h); off until paper data supports it

# --- bots (BOTS_SPEC.md): every dashboard seat is its own process talking over bus.db ---
BOTS_INLINE = False             # False: one OS process per seat; True: every seat stepped inside JEV's process (tests)
SCAN_EVERY_S = 120              # SCAN pulls the public feeds every 2 min
RISK_EVERY_S = 10               # RISK re-quotes open positions every 10 s (was 30 s in the single loop)
FILLS_EVERY_S = 15              # FILLS writes an equity snapshot of the book every 15 s
PIGGY_EVERY_S = 15
JEV_EVERY_S = 1
VET_LIMIT = 30                  # most coins VET checks per pass (each costs rugcheck + RPC calls)
SOCIAL_LIMIT = 8                # most coins SOCIAL reads per pass (DexScreener info + orders)
ORDER_MAX_AGE_S = 10            # 7 Gates #7 freshness: FILLS re-quotes any order older than this
MAX_CHASE_PCT = 15.0            # 7 Gates #6: FILLS kills a buy if the fresh quote is >15% above the signal price
JEV_LOSS_COOLDOWN_MIN = 30      # "hardcode a cooldown after every loss": JEV approves no entry for 30 min after a losing close (0 = off)
RISK_VOL_DECAY_RATIO = 0.20     # his RISK rule (savipww guides): 6h volume / (24h volume / 4) < 0.20 → close fully. None = off
# JEV's SOFT thresholds, pick lines and the no-X-handle size cut live in bots/questions.py (his thresholds.py numbers)
# --- honest coverage: a wall-clock jump between loop ticks means the box was paused (VM snapshot / sleep) ---
GAP_S = 90                      # JEV ticks every ~1 s, FILLS snapshots every 15 s: > 90 s between them = the desk was not running
# --- sell-simulation gate (VET/JEV hard gate sell_route_ok): Jupiter must quote a SELL of our ticket back to SOL ---
JUP_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
SOL_MINT = "So11111111111111111111111111111111111111112"
SELL_MAX_IMPACT = 0.05          # Jupiter priceImpactPct (fraction): fail above 5%
SELL_SLIPPAGE_BPS = 200
SELL_FALLBACK_DECIMALS = 6      # token decimals unknown: assume pump.fun's 6 (if the coin really has 9, the quote is 1000x smaller = a small test amount)
