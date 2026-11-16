"""One seat on the desk. Each bot has one job, reads its inbox on the bus, does periodic work in tick(),
keeps its own memory in bots/state/<name>.json and writes a heartbeat every step.
Only FILLS writes the paper book (state.json); every other bot reads it."""
import json, os, time
import store
from bots import bus


class Bot:
    name = "BOT"
    every = 5.0          # seconds between tick() calls
    job = ""

    def __init__(self, sid, cursor=0):
        self.sid, self.cursor, self.n, self.done = sid, cursor, 0, False
        self.status, self.last, self._t = "up", "started", 0.0
        self.mem = self.load_mem()

    # --- memory (per bot, never shared) ---
    def mem_path(self):
        d = os.path.join(os.path.dirname(os.path.abspath(store.STATE)), "bots_state"); os.makedirs(d, exist_ok=True)
        return os.path.join(d, self.name.lower() + ".json")

    def load_mem(self):
        try:
            m = json.load(open(self.mem_path()))
            return m if m.get("sid") == self.sid else {"sid": self.sid}
        except Exception:  # noqa
            return {"sid": self.sid}

    def save_mem(self):
        tmp = self.mem_path() + ".tmp"
        json.dump(self.mem, open(tmp, "w"), default=str); os.replace(tmp, self.mem_path())

    # --- talking ---
    def say(self, to, type, text, payload=None, task=None):
        self.last = text
        return bus.post(self.sid, self.name, to, type, text, payload, task)

    def book(self):
        return store.load_state()

    # --- work ---
    def on(self, m):       # handle one inbox message
        pass

    def tick(self):        # periodic job
        pass

    def finish(self):      # last words on shutdown
        pass

    def step(self):
        for m in bus.inbox(self.name, self.cursor):
            self.cursor = m["id"]
            if m["type"] == "shutdown":
                self.finish(); self.done = True; self.status = "off"
                break
            try:
                self.on(m)
            except Exception as e:  # noqa  a bad message never kills the seat
                self.say("JEV", "error", f"{self.name} error on {m['type']}: {str(e)[:90]}", task=m.get("task"))
        if not self.done and time.time() - self._t >= self.every:
            self._t = time.time()
            try:
                self.tick()
            except Exception as e:  # noqa
                self.say("JEV", "error", f"{self.name} tick error: {str(e)[:90]}")
        self.n += 1
        bus.beat(self.name, self.sid, self.status, self.last, self.n)
