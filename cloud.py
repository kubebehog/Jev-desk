"""Cloud paper sessions on GitHub Actions (kubebehog/Jev-desk). PAPER ONLY.
  python3 cloud.py start [--minutes 345] [--mode goal] [--goal 2000]   push the local book to branch `book`, dispatch session.yml
  python3 cloud.py status                                              latest runs + last book commit
  python3 cloud.py pull                                                back up local book, take the `book` branch copy, rebuild page data
Minutes > 345 run as chained legs (each leg flattens at its end). Token: env JEV_DESK_GH_TOKEN (never written to disk).
While cloud_run.json exists, local `desk.py start/setup` refuse; `pull` removes it once no run is active."""
import argparse, base64, datetime as dt, json, os, shutil, subprocess, sys, time
import requests
import store

REPO = "kubebehog/Jev-desk"
API = "https://api.github.com/repos/" + REPO
WF = "session.yml"
HERE = store.HERE
CLONE = os.path.join(HERE, ".cloud-book")
MARK = os.path.join(HERE, "cloud_run.json")
FILES = ("ledger.jsonl", "state.json")
ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")


def token():
    t = os.environ.get("JEV_DESK_GH_TOKEN")
    if not t: sys.exit("JEV_DESK_GH_TOKEN is not set")
    return t


def api(method, path, **kw):
    r = requests.request(method, API + path, timeout=30, headers={"Authorization": "Bearer " + token(), "Accept": "application/vnd.github+json"}, **kw)
    if r.status_code >= 400: sys.exit(f"github {method} {path}: {r.status_code} {r.text[:200]}")
    return r.json() if r.text else {}


def git(*a, check=True):
    hdr = "Authorization: Basic " + base64.b64encode(("x-access-token:" + token()).encode()).decode()
    r = subprocess.run(["git", "-c", "http.extraHeader=" + hdr, *a], cwd=CLONE if os.path.isdir(CLONE) else HERE, capture_output=True, text=True)
    if check and r.returncode: sys.exit(f"git {a[0]} failed: {r.stderr.strip()[:300]}")
    return r


def sync_clone():
    """.cloud-book = a clone sitting on origin/book (True) or on a fresh orphan `book` (False, no branch yet)."""
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        os.makedirs(CLONE, exist_ok=True); git("init", "-q"); git("remote", "add", "origin", f"https://github.com/{REPO}.git")
    has = git("fetch", "-q", "origin", "book", check=False).returncode == 0
    if has: git("checkout", "-q", "-B", "book", "FETCH_HEAD"); git("reset", "-q", "--hard", "FETCH_HEAD")
    return has


def active_runs():
    runs = api("GET", f"/actions/workflows/{WF}/runs?per_page=10").get("workflow_runs", [])
    return [r for r in runs if r["status"] in ACTIVE], runs


def local_session_running():
    import desk
    return desk.session_running(desk.migrate(store.load_state()))


def read(p):
    return open(p, "rb").read() if os.path.exists(p) else b""


def start(a):
    st = store.load_state()
    if local_session_running(): sys.exit("refusing: a local session is running (`desk.py stop` it first)")
    if st["positions"]: sys.exit(f"refusing: local book has {len(st['positions'])} open paper position(s); `desk.py close-all` first")
    act, _ = active_runs()
    if act: sys.exit(f"refusing: cloud run already {act[0]['status']}: {act[0]['html_url']}")
    has = sync_clone()
    if has and not read(os.path.join(HERE, "ledger.jsonl")).startswith(read(os.path.join(CLONE, "ledger.jsonl"))):
        sys.exit("refusing: the cloud book has entries the local ledger doesn't; run `python3 cloud.py pull` first")
    if not has:
        git("checkout", "-q", "--orphan", "book"); git("rm", "-rq", "--cached", ".", check=False)
    for f in FILES: shutil.copy(os.path.join(HERE, f), os.path.join(CLONE, f))
    git("add", *FILES)
    if git("diff", "--cached", "--quiet", check=False).returncode:
        git("-c", "user.name=jev-desk", "-c", "user.email=jev-desk@users.noreply.github.com", "commit", "-qm", f"book from box · {time.strftime('%Y-%m-%d %H:%M %Z')} · cash {st['cash']:.2f}")
        git("push", "-q", "origin", "HEAD:refs/heads/book"); print("book pushed from the box")
    else:
        print("book already up to date on github")
    inputs = {"minutes": str(int(a.minutes)), "mode": a.mode, "goal": "" if a.goal is None else str(a.goal)}
    t0 = time.time()
    api("POST", f"/actions/workflows/{WF}/dispatches", json={"ref": "main", "inputs": inputs})
    json.dump({"dispatched_ts": round(t0, 1), **inputs}, open(MARK, "w"))
    for _ in range(20):
        time.sleep(3)
        _, runs = active_runs()
        r = next((r for r in runs if r["event"] == "workflow_dispatch" and dt.datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).timestamp() >= t0 - 5), None)
        if r:
            print(f"cloud run {r['status']}: {r['html_url']} · {inputs['minutes']} min · mode {a.mode} · PAPER"); return
    print("dispatched; run not listed yet, check `python3 cloud.py status`")


def local_time(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def status(a):
    act, runs = active_runs()
    for r in runs[:3]:
        print(f"run {r['id']} · {r['status']}{'/' + r['conclusion'] if r.get('conclusion') else ''} · started {local_time(r['run_started_at'] or r['created_at'])} · {r['html_url']}")
    if not runs: print("no cloud runs yet")
    c = requests.get(API + "/commits?sha=book&per_page=1", headers={"Authorization": "Bearer " + token()}, timeout=30)
    if c.status_code == 200 and c.json():
        print(f"last book commit {local_time(c.json()[0]['commit']['committer']['date'])} · {c.json()[0]['commit']['message']}")
    else:
        print("no book branch yet")
    print("cloud owns the book (cloud_run.json)" if os.path.exists(MARK) else "box owns the book")


def pull(a):
    if not sync_clone(): sys.exit("no book branch on github yet")
    act, _ = active_runs()
    same = all(read(os.path.join(HERE, f)) == read(os.path.join(CLONE, f)) for f in FILES)
    if same:
        print("local book already matches the cloud book")
    else:
        bk = os.path.join(HERE, "backups", "pull-" + time.strftime("%Y%m%d-%H%M%S")); os.makedirs(bk, exist_ok=True)
        for f in FILES:
            if os.path.exists(os.path.join(HERE, f)): shutil.copy(os.path.join(HERE, f), bk)
        for f in FILES: shutil.copy(os.path.join(CLONE, f), os.path.join(HERE, f))
        print(f"pulled the cloud book · local copy backed up to {os.path.relpath(bk, HERE)}")
    logs = os.path.join(CLONE, "logs")
    if os.path.isdir(logs):
        d = os.path.join(HERE, "cloud_logs"); os.makedirs(d, exist_ok=True)
        for f in os.listdir(logs): shutil.copy(os.path.join(logs, f), d)
    if act:
        print(f"cloud run still {act[0]['status']} ({act[0]['html_url']}): this is a mid-run copy; cloud keeps owning the book")
    elif os.path.exists(MARK):
        os.remove(MARK); print("no cloud run active: the box owns the book again")
    L = store.read_ledger()
    ss = [x for x in L if x["kind"] == "session_start"]
    if ss:
        s = ss[-1]; end = next((x for x in reversed(L) if x["kind"] == "session_end" and x["sid"] == s["sid"]), None)
        eq = [x["equity"] for x in L if x["kind"] == "equity" and x.get("sid") == s["sid"]]
        print(f"last session {s['sid']} · PAPER · start ${s['start_equity']:,.2f} · " + (f"end ${end['equity']:,.2f} ({end['why']})" if end else f"latest ${eq[-1]:,.2f} (running)" if eq else "no equity yet")
              + f" · {len(eq)} equity lines")
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_page_data.py")], cwd=HERE, capture_output=True, text=True)
    print("page data rebuilt" if r.returncode == 0 else "build_page_data failed: " + r.stderr[-300:])


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start"); s.add_argument("--minutes", type=float, default=345); s.add_argument("--mode", default="goal"); s.add_argument("--goal", type=float)
    sp.add_parser("status"); sp.add_parser("pull")
    a = ap.parse_args()
    if a.cmd == "start":
        import config
        if a.mode not in config.MODES: sys.exit(f"mode must be one of {config.MODES}")
        if not 1 <= a.minutes <= 720: sys.exit("minutes must be 1..720 (legs of 345 chain on their own)")
    {"start": start, "status": status, "pull": pull}[a.cmd](a)


if __name__ == "__main__":
    main()
