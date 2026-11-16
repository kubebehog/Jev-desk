"""python3 -m bots.run SEAT SID CURSOR JEV_PID   (started by JEV; one OS process per seat)
Exits on 'shutdown', or when JEV's process is gone (orphan guard: FILLS flattens the book first)."""
import os, sys, time
from bots import bus
from bots.jev import SEATS


def jev_alive(pid):
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


def main():
    name, sid, cursor, jev_pid = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    bot = next(c for c in SEATS if c.name == name)(sid, cursor)
    bot.say("JEV", "hello", f"{name} up · pid {os.getpid()} · job: {bot.job}")
    while not bot.done:
        bot.step()
        if not jev_alive(jev_pid):
            if name == "FILLS":
                left = bot.flatten("JEV gone: orphan guard flatten, no session watching")
                bot.say("*", "flat", f"JEV process gone → orphan guard flattened · {len(left)} left")
            bot.status = "off"; bus.beat(name, sid, "off", "JEV gone, exiting", bot.n)
            break
        time.sleep(0.5)
    bus.beat(name, sid, "off", bot.last, bot.n)


if __name__ == "__main__":
    main()
