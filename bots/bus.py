"""The desk bus: one sqlite file (bus.db, next to state.json). Every message has
id, ts, sid, frm, to, type, task, text, payload. `to` is a bot name or "*" (everyone).
`task` is the coin's mint (or another id) and stays the same at every stage, so a
candidate can be followed SCAN -> VET -> SOCIAL -> JEV -> SIZE -> FILLS -> RISK in one query.
Heartbeats live in the same file (table hb). sqlite WAL handles the many-writer case."""
import json, os, sqlite3, time
from contextlib import closing
import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS msg(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sid TEXT, frm TEXT, too TEXT,
                               type TEXT, task TEXT, text TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS msg_too ON msg(too, id);
CREATE TABLE IF NOT EXISTS hb(bot TEXT PRIMARY KEY, ts REAL, sid TEXT, pid INTEGER, status TEXT, last TEXT, n INTEGER);
"""


def path():
    return os.path.join(os.path.dirname(os.path.abspath(store.STATE)), "bus.db")


def db():
    c = sqlite3.connect(path(), timeout=15, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=15000")
    c.executescript(SCHEMA)
    return c


def _row(r):
    return {"id": r[0], "ts": r[1], "sid": r[2], "frm": r[3], "to": r[4], "type": r[5], "task": r[6], "text": r[7],
            "payload": json.loads(r[8]) if r[8] else None}


def post(sid, frm, to, type, text, payload=None, task=None):
    with closing(db()) as c:
        cur = c.execute("INSERT INTO msg(ts,sid,frm,too,type,task,text,payload) VALUES(?,?,?,?,?,?,?,?)",
                        (round(time.time(), 3), sid, frm, to, type, task, text,
                         json.dumps(payload, separators=(",", ":"), default=str) if payload is not None else None))
        return cur.lastrowid


def inbox(bot, after_id):
    with closing(db()) as c:
        return [_row(r) for r in c.execute("SELECT * FROM msg WHERE id>? AND (too=? OR too='*') ORDER BY id", (after_id, bot))]


def last_id():
    with closing(db()) as c:
        return c.execute("SELECT COALESCE(MAX(id),0) FROM msg").fetchone()[0]


def recent(n=60, sid=None, after_id=0, with_payload=False):
    q = "SELECT * FROM msg WHERE id>?" + (" AND sid=?" if sid else "") + " ORDER BY id DESC LIMIT ?"
    with closing(db()) as c:
        rows = [_row(r) for r in c.execute(q, (after_id, sid, n) if sid else (after_id, n))]
    if not with_payload:
        for r in rows: r["payload"] = None
    return rows[::-1]


def find(sid=None, **eq):
    """All messages matching e.g. frm='VET', type='vetted' (for proofs and tests)."""
    where, args = ["1=1"], []
    if sid: where.append("sid=?"); args.append(sid)
    for k, v in eq.items():
        where.append(("too" if k == "to" else k) + "=?"); args.append(v)
    with closing(db()) as c:
        return [_row(r) for r in c.execute("SELECT * FROM msg WHERE " + " AND ".join(where) + " ORDER BY id", args)]


def beat(bot, sid, status, last, n):
    with closing(db()) as c:
        c.execute("INSERT OR REPLACE INTO hb(bot,ts,sid,pid,status,last,n) VALUES(?,?,?,?,?,?,?)",
                  (bot, round(time.time(), 3), sid, os.getpid(), status, last[:160], n))


def beats():
    with closing(db()) as c:
        return {r[0]: {"ts": r[1], "sid": r[2], "pid": r[3], "status": r[4], "last": r[5], "n": r[6]}
                for r in c.execute("SELECT * FROM hb")}
