"""Append-only ledger + state file. Nothing in here ever rewrites ledger.jsonl."""
import json, os, time
import config

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger.jsonl")
STATE = os.path.join(HERE, "state.json")


def now():
    return round(time.time(), 3)


def append(kind, **data):
    rec = {"ts": now(), "kind": kind, "paper": True, **data}
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return rec


def log(agent, msg, **extra):
    print(f"[{time.strftime('%H:%M:%S')}] {agent:8s} {msg}", flush=True)
    return append("log", agent=agent, msg=msg, **extra)


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER) as f:
        return [json.loads(l) for l in f if l.strip()]


def default_state():
    return {"paper": True, "mode": "goal", "goal_usd": config.DEFAULT_GOAL_USD, "start_usd": config.START_BALANCE_USD,
            "cash": config.START_BALANCE_USD, "positions": {}, "halted": False, "picks": [], "one_coin": None,
            "bags": [], "holder_hist": {}, "price_hist": {}, "created": now()}


def load_state():
    if not os.path.exists(STATE):
        s = default_state()
        save_state(s)
        append("start", start_usd=s["cash"], mode=s["mode"], goal_usd=s["goal_usd"])
        return s
    with open(STATE) as f:
        return json.load(f)


def save_state(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)
