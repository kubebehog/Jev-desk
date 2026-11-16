"""PIGGY: guards the vault. Compounder lock (cash hits lock_at x start -> the start goes in the vault for good),
goal / paycheck line watch (tells JEV), and the paper 'withdraw' line at session end (nothing to withdraw: PAPER)."""
import config, market, risk
from bots.base import Bot


class Piggy(Bot):
    name, every, job = "PIGGY", config.PIGGY_EVERY_S, "guards the vault · watches the goal"

    def tick(self):
        st = self.book(); S = st.get("session") or {}
        q = market.quotes(set(st["positions"])); eq = risk.equity(st, q)
        R = risk.rules(st["mode"])
        if R.get("lock_at") and not st.get("vault") and not self.mem.get("locked") and st["cash"] >= R["lock_at"] * S.get("start_equity", 0):
            self.mem["locked"] = True
            self.say("FILLS", "lock", f"cash ${st['cash']:,.2f} hit {R['lock_at']:.0f}x start → lock ${S['start_equity']:,.2f}",
                     {"usd": round(S["start_equity"], 2), "why": f"cash hit {R['lock_at']:.0f}x, ${S['start_equity']:.2f} locked in the vault, only house money rides"})
        goal = S.get("goal_usd")
        if goal and eq >= goal and not self.mem.get("goal_told"):
            self.mem["goal_told"] = True
            self.say("JEV", "goal_hit", f"equity ${eq:,.2f} ≥ goal ${goal:,.2f}", {"equity": eq, "goal": goal, "mode": st["mode"]})
        self.save_mem()
        self.status = f"vault ${st.get('vault', 0):,.0f}"
        self.last = f"equity ${eq:,.2f}" + (f" · goal {100*eq/goal:.0f}% of ${goal:,.0f}" if goal else " · no goal") + f" · vault ${st.get('vault', 0):,.2f} · PAPER"

    def on(self, m):
        if m["type"] == "session_end":
            st = self.book()
            self.say("*", "vault", f"vault ${st.get('vault', 0):,.2f} · cash ${st['cash']:,.2f} · withdraw: PAPER, nothing to withdraw, no wallet connected")
