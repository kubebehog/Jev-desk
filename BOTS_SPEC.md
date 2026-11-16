# BOTS_SPEC: the desk's bots, JEV, and how they talk (PAPER ONLY)

Built from @Hrundel75's posts and the articles he links. Every claim is tagged:
- **[V]** verified: quoted or paraphrased from the source given.
- **[I]** inferred: our reading or our adaptation, not stated in the source.

Code and prompt blocks inside the X articles are exposed by the API (`article.entities.code`). All of them are saved in
`/workspace/hrundel/articles/code_blocks.md` (11 articles, 133 blocks). Full post text is in `posts_fulltext.md` and `raw/fulltext_recovered.md`.

Main sources:
- **[A]** "Jev as the judge" core article: https://x.com/Hrundel75/status/2103764774127317363 (2026-09-26)
- **[B]** "The Grok Bot Trading Terminal That Printed $89 Into $7,769" (six-bot desk, by @savipww, linked in his posts): https://x.com/i/status/2095171104004575708
- **[C]** "Megabrain (Jev) & Six Grok Bots" (Jev setup guide, @savipww): https://x.com/i/status/2102720919185617314
- **[D]** "The Hedge Fund Terminal…" (eight seats + QuantGPT): https://x.com/i/status/2110007684976030097
- **[E]** "Grok Bot Pre-Flight: 7 Gates": https://x.com/i/status/2117908942013481205
- **[F]** "The Grok Bot Playbook" (chief, handoffs, approvals): https://x.com/i/status/2114701030340300848
- **[G]** Courtroom post: https://x.com/Hrundel75/status/2103852838342275331
- **[H]** Six agents, "jev only fires when 4 of 6 agents agree": https://x.com/Hrundel75/status/2107468891542716464
- **[J]** "jev reads the line and decides. nothing else can buy … money moves through jev, with a size limit": https://x.com/Hrundel75/status/2108901142264487999
- **[T]** TypeSafe docs: https://docs.typesafe.ai

## 1. What JEV is

- **[V]** Jev is TypeSafe AI's "System One" decision model. "You ask a typed question and it returns a choice, a score or a probability instead of an essay, in a fraction of a second" [A].
- **[V]** API: `POST https://api.typesafe.ai/v1/systemone` with `model: jev-latest`, input $0.042 per million tokens, output free, 1,200 requests per minute, and a `TYPESAFE_API_KEY` [C block 4/12, T]. Answer types are noul (yes/no probability), score and choice (with probabilities). Example: `{"model":"jev-1.13.0","answers":{"urgent":{"type":"noul","noul":0.95}}}` [C].
- **[V]** Its role is the judge. "The one who talks never decides." The talker (Claude/Grok) pitches; Jev "answers one question about each pitch: is this real?" "Over 36 hours, Claude wanted in 212 times. Jev let it 19 times" [A].
- **[V]** In the courtroom, Jev is the JUDGE: it "reads both, never says a word, returns a number". The other seats are PROSECUTOR, DEFENSE, BAILIFF ("never more than a fifth of the bank") and EXECUTIONER [A, G].
- **[V]** The anti-you score: "how much does this look like him? Above 0.80, the trade is banned. No exceptions" [A].
- **[V]** Rules live in code, not prompts: "the gate threshold, the maximum size per trade, the cooldown after a loss, the kill switch, the daily budget" [A].
- **[V]** In the desk guides, CHIEF is the seat that asks Jev: "YOU DO NOT FORM OPINIONS ABOUT TOKENS. YOU CALL THE JUDGE" [C block 10]. judge.py holds the only TypeSafe key, and the bots use a desk secret [C block 28]. "jev · picks, never trades" appears on his OINK desk frame.
- **What we built [I]:** we have no TypeSafe key. Getting one needs an account at console.typesafe.ai, which needs Tomer, so it was not set up. Our **JEV** asks the same typed questions, but each answer is a **fixed local rule** (`bots/questions.py`, `MODEL = "local-rules-1 (not TypeSafe Jev: no key)"`). The numbers are rule outputs, not calibrated probabilities, and the app labels them that way. JEV also replaces every "TOMER"/"my" label as the chief. Its lines (decisions, morning message, recap) are templates filled from the ledger, so JEV writes no model prose. That matches "Jev never writes a word".

## 2. The seats (his spec, then ours)

| Seat | His job [source] | Inputs / thresholds [V] | Output [V] | Ours (`bots/*.py`) [I] |
|---|---|---|---|---|
| **JEV (CHIEF)** | Runs the room and never opens, sizes or closes. Calls the judge once per candidate set, then `pick`. "No trade is a result" [B block 1, C blocks 6/10/20] | SOFT lines: concentration ≤0.55, momentum_spent ≤0.60, liquidity_fits ≥0.60, account_is_project ≥0.70, recycled ≤0.50, dev_loaded ≤0.55, crowd ≥0.55, PICK worth ≥0.60, conf ≥0.55; never pick on one survivor; no X handle → size ×0.60 [C block 29/6/17] | Order `{order_id, token, size_factor, confidence, why, model}` [C block 14]; Telegram line | `jev.py` + `questions.py`. Asks market (shape, liquidity_fits_ticket, momentum_already_spent), solana (authority_risk, concentration_is_exit_risk, dev_still_loaded), social (account_is_the_project) and about_me (looks_like_my_losses ≤0.80) [A]. Then the mode signal and pick. Sends the order to SIZE in his order shape, or says "none" with the kill counts. Benches kills with VET. Vetoes during the 30-min cooldown after a loss [A: "within 30 minutes of a loss"]. Supervises: starts the 7 processes, restarts a dead seat, winds down |
| **SCAN** | "Produce a ranked candidate list. You never decide to buy" [B block 7] | DexScreener launch data; holders climbing faster than price; liquidity floor; never pad the list [B] | Up to 10 rows `{ticker, contract, liquidity_usd, volume_h1, …, degraded}` | `scan.py`: PumpPortal websocket + DexScreener feeds, every 120 s. Shortlist = liq ≥ $20K or CTO, up to 30 by 1h volume → VET "candidates" |
| **VET** | "You kill candidates. You are measured on what you correctly refuse." Cheapest check first, first failure ends it. Failed call = REJECT [B block 2]. Log every rejection; bench on the failed check [C blocks 16/27] | Top wallet >5% reject; liquidity floor; holders flat while price climbs; already priced; age/shape [B]. 7 Gates: authority, liquidity ≤2% of pool, holders (real top-10 ≤30%), creator history, chase >15% / impact >3%, data >10 s old → fail closed [E] | `{verdict PASS/REJECT, failed_check, evidence}` | `vet.py`: rugcheck + Solana RPC (mint authority, dev wallet, top wallet ≤6%, top-10 ≤30% with pools excluded, LP locked, bundle proxy, liq/age/vol) plus 3 soft numbers. UNKNOWN = fail. **Bench by reason** using his BENCH_MINUTES (facts 100,000 min, concentration 90, shape/liquidity 25, UNKNOWN 10). Candles for the top 5 → SOCIAL "vetted" |
| **SOCIAL** | Took BOOK's chair in the Jev guide. Handle from the chain; "no handle is a gap, not a pass"; questions account_is_the_project / audience_is_real / recycled_account / effort [C block 11] | `x_account` read | Answers to JEV | `social.py`: DexScreener project links (X handle, community, Telegram, site), active boosts, paid profile/CTO orders. **No X account reading** (audience/recycled/effort are not asked; see §5) → JEV "social" |
| **SIZE** | "One question: how many dollars. Never whether, never when" [B block 3]. ticket = kelly × bank capped at 6%; × size_factor; ≤2% of liquidity; below the fee floor → 0 [C block 2] | Free cash only, never the locked bag [B] | `{dollars, percent_of_free_cash, exitable, ceiling_applied, why}` | `size.py`: mode slice × size_factor, then the desk's entry guards (20% cap, % of pool, max open, already held) → FILLS "order" or JEV "skip". Fixed slice = his COLD sizer ("after a win: same. After a loss: same") [A] |
| **FILLS** | "Get the decided order done and report honestly. You never reconsider." One venue (FOMO); fee floor max(0.45%×$, $0.95); slippage flagged loudly [B block 8, C block 2] | — | `{filled, fill_price, slippage_bps, partial}` | `fills.py`: **the only writer of the book**. PAPER fills on a live DexScreener quote (fresh quote if the order is >10 s old; rejects a chase >15% [E]). Handles flatten, vault lock and the equity ledger. No FOMO: there is no public API and logging in is off-limits |
| **RISK** | "Final authority. Nobody overrules you." Volume rule: 6h volume <20% of the 24h average → CLOSE fully within 60 s; poll every 5 min [B block 9, C block 2] | — | `{action, rule_fired, ratio, pnl_usd}` | `risk_bot.py` every 10 s: the desk's stop/trail/ladder (his later mode posts) **plus his volume-decay rule** (`RISK_VOL_DECAY_RATIO = 0.20`) → FILLS "order" SELL |
| **PIGGY** | Vault seat on his OINK frame ("stuffs the profit into the vault") [posts_fulltext] | — | — | `piggy.py`: equity vs goal → JEV "goal_hit"; compounder lock → FILLS "lock"; at session end "vault … withdraw: PAPER, nothing to withdraw" |

Not built [I]:
- BOOK (prediction markets: Polymarket/Kalshi gap ≥8%) [B block 5]. It is out of scope for a memecoin paper desk, and his Jev guide replaced it with SOCIAL.
- QUANT/STOCKS seats [D]. They need a QuantGPT account and Alpaca.
- PROSECUTOR/DEFENSE talkers [A]. Our pipeline is rules over evidence. There is no LLM talker to cross-examine, which follows his advice "the judge scores the evidence, not the prose".

## 3. How his bots communicate [V] → our bus [I]

- **[V]** Work moves in order: SCAN → VET → (BOOK) → SIZE → FILLS → RISK. "RISK runs on its own timer … never queued behind anyone." CHIEF pings every 60 s; two missed pings means restart once; the same box dying twice in an hour halts the desk [B block 1].
- **[V]** "Every handoff carries the same five fields": TASK ID, OWNER, INPUTS, EVIDENCE, OPEN. One ID follows the work through every bot [F block 1]. The chief "is the only bot you talk to … delegate … if a task needs two of them, have them talk and report back" [F block 15].
- **[V]** "NOBODY RE-READS `why`. It is there for the log … What is left is arithmetic." "NO ORDER IS ALSO AN ORDER" [C block 20].
- **[V]** Reports go to Telegram ("never to a dashboard nobody opens"). Message the human mid-session only when a number moves more than 10% [B block 1].

**Our bus** (`bots/bus.py`, sqlite WAL, `bus.db` next to `state.json` in the desk folder):

`msg(id, ts, sid, frm, too, type, task, text, payload JSON)` + heartbeats `hb(bot, ts, sid, pid, status, last, n)`.

| His field | Ours |
|---|---|
| TASK ID | `task` = the coin's mint, the same through every stage |
| OWNER | `to` |
| INPUTS / EVIDENCE | `payload` (rows, checks, typed answers, quotes) |
| OPEN | `type` (the next seat's job) |

The human-readable `text` is what the desk chat shows.

Message types:
- `hello` and heartbeats every step;
- `candidates` (SCAN→VET), `vetted` (VET→SOCIAL), `social` (SOCIAL→JEV);
- `pick` (JEV→SIZE, carrying his order JSON), `order` (SIZE→FILLS, RISK→FILLS, JEV→FILLS for your pick);
- `filled` (FILLS→*), `skip`, `bench` (JEV→VET), `veto` / `decision` (JEV→*);
- `goal_hit`, `lock`/`locked` (PIGGY↔FILLS);
- `flatten`/`flat`, `session_start` / `session_end` / `shutdown`, `recap` / `morning`.

Each seat is its own OS process (`python -m bots.run NAME SID …`) with its own memory file (`bots_state/NAME.json`). JEV is the parent. If JEV dies, every seat notices (orphan guard), FILLS flattens, and all seats exit.

## 4. Plugins and connectors for the traders talking (recommendation only, nothing connected)

| Option | What it is | Fit |
|---|---|---|
| **Our sqlite bus (built)** | Local, durable, zero accounts, every message logged | **Use now.** Gives proof per seat; the app shows it as Desk chat |
| Grok Bot group chats (docs.x.ai/grok-bot/chat-and-collaboration) | 2–6 Grok bots in one room, async handoffs, text only; each reply counts toward usage | Good for a human-visible "room" like his Telegram desk. Needs Tomer to create the room, and costs usage per message. Rules forbid us messaging other bots, so **not done** |
| Telegram bot (what he uses) | End-of-day report plus >10% moves to a chat | Needs Tomer's Telegram account/BotFather token. Recommend as the outward report channel |
| Discord webhook | Same idea | Needs Tomer's server |
| A2A protocol (a2a-protocol.org, Linux Foundation) | Agent-to-agent standard (agent cards, tasks, messages) | Right standard if the seats ever become separate hosted agents. Overkill for one box |
| MCP | Gives a model *tools*, not peer messaging | Use for tools (e.g. TypeSafe/QuantGPT MCP), not for the bus |
| NATS / Redis Streams / Kafka | Networked brokers | Only if seats move to different machines; sqlite is enough on one box |
| ntfy (already wired) | Push to the phone | Keep for sell alerts / the morning message |

Recommendation: keep the sqlite bus internally. If Tomer wants an outside room, the next step is one Telegram bot for the CHIEF report and >10% moves, which needs Tomer to create the bot token. A Grok Bot group chat is the in-product alternative.

## 5. Not possible with public data / our limits (honest list)

- **Jev itself:** no TypeSafe key (needs an account). JEV answers are local rules, not calibrated.
- **X reading by the bot processes:** SOCIAL cannot read X accounts or mentions. That needs Tomer's X connector, and running it every 2 min would burn the quota. So audience_is_real / recycled_account / effort are not asked, and coins without a project-published handle get ×0.60 [C].
- **FOMO** (his only venue): no public API, and logging in is forbidden. FILLS is PAPER on DexScreener quotes.
- **Sell simulation** (7 Gates #2) and **creator history** (#5): no free public endpoint. Not checked; marked unchecked.
- **Holder-count growth:** only from rugcheck's totalHolders as VET re-checks a coin, so short sessions often lack it. The `shape` question then leans on buys/sells.
- **BOOK, QUANT, STOCKS** seats: not built (prediction markets; QuantGPT + Alpaca accounts).
- **His results** ($89 → $7,769, etc.) are his claims, not verified, and nothing here targets them.
