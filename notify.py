"""Phone push via ntfy.sh on a random topic. PAPER alerts only.
Publishing is OFF until `python3 desk.py push on` (an outside post needs the user's go-ahead).
While off, every alert is written to outbox.jsonl exactly as it would be sent."""
import json, os, secrets, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "notify.json")
OUTBOX = os.path.join(HERE, "outbox.jsonl")


def cfg():
    if not os.path.exists(CFG):
        c = {"topic": "desk-paper-" + secrets.token_urlsafe(18).replace("_", "x").replace("-", "y"), "enabled": False}
        json.dump(c, open(CFG, "w"), indent=1)
    return json.load(open(CFG))


def set_enabled(on):
    c = cfg(); c["enabled"] = bool(on); json.dump(c, open(CFG, "w"), indent=1); return c


def push(text, title="Trading Desk · PAPER", tags="pig"):
    c = cfg()
    rec = {"ts": round(time.time(), 3), "topic": c["topic"], "title": title, "text": text, "sent": False}
    if c["enabled"] and not os.environ.get("DESK_NO_PUSH"):   # DESK_NO_PUSH=1 in the cloud runner: never post
        try:
            r = requests.post("https://ntfy.sh/" + c["topic"], data=text.encode(), timeout=10,
                              headers={"Title": title.encode("ascii", "ignore").decode(), "Tags": tags})
            rec["sent"] = r.status_code == 200
            rec["status"] = r.status_code
        except Exception as e:  # noqa
            rec["error"] = str(e)[:80]
    with open(OUTBOX, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec
