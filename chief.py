"""CHIEF OF STAFF: one sentence -> setup card. Pure parsing, no network."""
import datetime as dt
import re
import config

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "grand": 1000, "thousand": 1000}


def amounts(text):
    """'$500' -> 500, 'two fifty' -> 250, 'twenty four hundred' -> 2400, 'four grand' -> 4000, 'ten bucks' -> 10."""
    t = text.lower().replace(",", "")
    out = [float(m) for m in re.findall(r"\$\s?(\d+(?:\.\d+)?)", t)]
    out += [float(m) * (1000 if k else 1) for m, k in re.findall(r"\b(\d+(?:\.\d+)?)\s?(k)?\s?(?:bucks|dollars|usd)\b", t)]
    toks, cur, nums = re.findall(r"[a-z]+", t), [], []
    for w in toks + ["."]:
        if w in WORDS:
            cur.append(WORDS[w]); continue
        if cur:
            v = 0
            for n in cur:
                if n in (100, 1000):
                    v = (v or 1) * n
                elif v and v % 100 == 0 and v >= 100:
                    v += n
                elif v and n >= 10 and len(cur) == 2 and cur[0] < 10 and n % 10 == 0:  # "two fifty" -> 250
                    v = v * 100 + n
                else:
                    v += n
            nums.append(float(v)); cur = []
    return out + nums


def end_time(text, now):
    t = text.lower()
    if "overnight" in t or "tonight" in t or "while i sleep" in t:
        e = now.replace(hour=7, minute=0, second=0, microsecond=0)
        return (e if e > now else e + dt.timedelta(days=1)), "overnight"
    if re.search(r"9\s?(-|to)\s?5|clock out|today|all day|work", t):
        e = now.replace(hour=17, minute=0, second=0, microsecond=0)
        return (e if e > now else now + dt.timedelta(hours=8)), "9-5"
    m = re.search(r"(\d+)\s?(min|minutes|h|hours)\b", t)
    if m:
        n = int(m.group(1)); return now + dt.timedelta(minutes=n if m.group(2).startswith("m") else n * 60), "custom"
    return now + dt.timedelta(hours=8), "custom"


def parse(text, now=None):
    now = now or dt.datetime.now()
    t = text.lower()
    nums = amounts(text)
    mode, goal = "goal", None
    if "degen" in t or "new launch" in t:
        mode = "degen"
    if re.search(r"before (they|it) (hit|land)s? trending|pre.?trending|radar", t): mode = "pre-trending"
    if re.search(r"rugged|cto|takeover", t): mode = "cto-watch"
    if re.search(r"fix my bags|bags", t): mode = "fix-bags"
    if re.search(r"i pick|you do the selling|sell for me", t): mode = "sell-for-me"
    if re.search(r"\bonly \w+ today|one coin|buy every dip", t): mode = "one-coin"
    if re.search(r"paycheck", t): mode = "paycheck"
    if re.search(r"compound|lock.at|\block\b", t): mode = "compound"
    if re.search(r" into | and stop|then stop|goal|cover|pay off", t) and mode in ("goal", "degen"):
        mode = "goal"
    budget = nums[0] if nums else None
    if mode in ("goal", "paycheck") and len(nums) >= 2:
        goal = nums[1]
    coin = None
    m = re.search(r"\bonly (\w+) today", t)
    if mode == "one-coin" and m: coin = m.group(1).upper()
    end, kind = end_time(text, now)
    if (end - now).total_seconds() > config.MAX_SESSION_HOURS * 3600:
        end = now + dt.timedelta(hours=config.MAX_SESSION_HOURS)
    R = config.MODE_RULES[mode]
    return {"sentence": text, "budget": budget, "mode": mode, "goal_usd": goal, "coin": coin, "session": kind,
            "end": end.strftime("%Y-%m-%d %H:%M"), "end_ts": end.timestamp(),
            "stop": f"{R['stop']}% per trade" + (", moves to entry once green" if R.get("breakeven") else ""),
            "take_profit": f"trailing {R['trail']}%" + ("".join(f" · {f*100:.0f}% at x{1+g/100:.1f}" for g, f in R["ladder"])),
            "max_open": R["max_open"], "size": f"{R['size']*100:.0f}% of free cash" if R["size"] else "your picks only",
            "withdrawals": "PAPER — nothing to withdraw, no wallet connected", "rules": R["text"]}


def card(c, equity=None):
    rows = [("Budget", f"${c['budget']:,.2f} PAPER" if c["budget"] else f"current paper equity ${equity:,.2f}" if equity else "—"),
            ("Mode", c["mode"] + (f" {c['coin']}" if c.get("coin") else "")), ("Session", f"{c["session"]} · ends {c['end']} Asia/Jerusalem"),
            ("Stop loss", c["stop"]), ("Take profit", c["take_profit"]), ("Max open", f"{c['max_open']} positions"),
            ("Size", c["size"]), ("Goal", f"${c['goal_usd']:,.2f}" if c.get("goal_usd") else "none"), ("Withdrawals", c["withdrawals"])]
    w = max(len(k) for k, _ in rows)
    return "TRADING DESK · SETUP (PAPER)\n" + "\n".join(f"{k.ljust(w)}  {v}" for k, v in rows) + f"\nRules: {c['rules']}"


if __name__ == "__main__":
    for s in ["trade overnight $500 degen", "Turn twenty into rent twenty four hundred and stop", "Two fifty beat my paycheck before I clock out",
              "Only rambo today buy every dip sell every pop", "Fix my bags I lost four grand on these", "I pick the coins you do the selling",
              "Get me in before they hit trending", "Buy the ones the dev already rugged", "Thirty bucks get it to sixty, compound"]:
        c = parse(s); print(s, "->", c["mode"], c["budget"], c["goal_usd"], c["session"], c["coin"])
