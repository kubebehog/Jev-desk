#!/usr/bin/env bash
# Copy the book (ledger up to its last full line, state, session logs) into the `book` worktree and push it.
set -e
cd "$(dirname "$0")/.."
python3 - <<'PY'
d = open("ledger.jsonl", "rb").read(); open("book/ledger.jsonl", "wb").write(d[:d.rfind(b"\n") + 1])
PY
cp state.json book/state.json
mkdir -p book/logs; cp session-*.log book/logs/ 2>/dev/null || true
cd book
git add -A
git diff --cached --quiet && { echo "book: nothing new ($1)"; exit 0; }
EQ=$(python3 -c "import json; print(next((r['equity'] for r in map(json.loads, reversed(open('ledger.jsonl').readlines())) if r['kind']=='equity'), '?'))")
git -c user.name="jev-desk" -c user.email="jev-desk@users.noreply.github.com" commit -qm "book $1 · $(date '+%H:%M %Z') · run $GITHUB_RUN_ID · paper equity $EQ"
git push -q origin book && echo "book pushed ($1)"
