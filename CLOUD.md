# Cloud sessions (GitHub Actions) · PAPER ONLY

Why: the box pauses when no bot is working (night of 2026-11-16: awake 4.6 of 372 min). A GitHub runner doesn't.

Where: private repo `kubebehog/Jev-desk`. Branch `main` = code only (export of this folder, no keys, no ntfy topic,
no app/). Branch `book` = the data: `ledger.jsonl`, `state.json`, `logs/`. Workflow `.github/workflows/session.yml`.

    python3 cloud.py start --minutes 360 --mode goal [--goal 2000]   # push the box's book to `book`, dispatch the run
    python3 cloud.py status                                          # latest runs + last book commit (Asia/Jerusalem)
    python3 cloud.py pull                                            # back up local book, take `book`'s copy, rebuild page data

How a run works: checkout main → copy the book from `book` → check DexScreener/RugCheck/GeckoTerminal/Jupiter/RPC answer
→ `desk.py start --foreground` (same JEV + 7 seats as on the box) → a background loop commits the book to `book` at 2 min, then
every 10 min → final step (`if: always()`, also on failure/cancel) flattens anything still open on paper and commits.
Push alerts are forced off in the cloud (`DESK_NO_PUSH=1`).

Long sessions: one job is capped at 345 session minutes (timeout 355). `--minutes` up to 720 runs as chained legs:
when a leg ends with time left it dispatches the next leg with the remaining minutes (same mode/goal). Each leg
flattens at its end and the next starts flat from the committed book, so positions never carry across legs; the gap
between legs is the queue + setup time, usually 1-3 min. A goal hit or a stop ends the chain.

Ownership: `cloud.py start` refuses if a local session runs, the local book has open positions, a cloud run is active,
or the cloud book has entries the box hasn't pulled. It writes `cloud_run.json`; while that exists, `desk.py start/setup`
refuse on the box. `cloud.py pull` removes it once no cloud run is active. Re-running `pull`/`start` is safe.

Token: env `JEV_DESK_GH_TOKEN` (fine-grained, this repo only), used per command, never stored in git config or files.
Free minutes: a private repo gets 2,000 Actions min/month, so a 345-min leg is ~5.8 nights a month.
