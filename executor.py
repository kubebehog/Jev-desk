"""EXECUTOR: paper fills only. Fill = live DexScreener quote +/- (base slip + price impact), minus fee per side.
There is no code path that signs, sends, or touches a wallet."""
import time
import config, store


def slip_pct(ticket_usd, liq_usd):
    impact = 100.0 * ticket_usd / max(liq_usd / 2.0, 1.0)
    return min(config.BASE_SLIP_PCT + impact, config.MAX_SLIP_PCT)


def paper_buy(state, row, usd, reason, mode, agent="Sniper"):
    assert config.PAPER
    usd = round(min(usd, state["cash"]), 2)
    if usd < 1 or row["price"] <= 0:
        return None
    sp = slip_pct(usd, row["liq"])
    fill = row["price"] * (1 + sp / 100)
    fee = usd * config.FEE_PCT_PER_SIDE / 100
    qty = (usd - fee) / fill
    state["cash"] = round(state["cash"] - usd, 6)
    pos = {"mint": row["mint"], "symbol": row["symbol"], "mode": mode, "entry_quote": row["price"], "entry_fill": fill,
           "qty": qty, "qty0": qty, "cost_usd": usd, "realized_usd": 0.0, "peak": row["price"], "tp_done": 0,
           "opened": time.time(), "liq_at_entry": row["liq"], "url": row.get("url")}
    state["positions"][row["mint"]] = pos
    store.append("trade", side="BUY", mint=row["mint"], symbol=row["symbol"], mode=mode, quote=row["price"], fill=fill,
                 slip_pct=round(sp, 3), fee_usd=round(fee, 4), usd=usd, qty=qty, reason=reason, agent=agent, mcap=row.get("mcap"))
    store.log("executor", f"PAPER BUY {row['symbol']} ${usd:.2f} @ {fill:.8g} (quote {row['price']:.8g}, slip {sp:.2f}%, fee ${fee:.2f}) - {reason}")
    return pos


def paper_sell(state, mint, frac, quote, liq, reason, agent="Exit", mcap=None):
    assert config.PAPER
    pos = state["positions"][mint]
    qty = pos["qty"] if frac >= 0.999 else min(pos["qty"], pos["qty0"] * frac)
    gross_est = qty * quote
    sp = slip_pct(gross_est, liq)
    fill = quote * (1 - sp / 100)
    gross = qty * fill
    fee = gross * config.FEE_PCT_PER_SIDE / 100
    net = gross - fee
    basis = pos["cost_usd"] * qty / pos["qty0"]
    pnl = net - basis
    pos["qty"] -= qty
    pos["realized_usd"] += pnl
    state["cash"] = round(state["cash"] + net, 6)
    closed = pos["qty"] <= pos["qty0"] * 1e-6
    store.append("trade", side="SELL", mint=mint, symbol=pos["symbol"], mode=pos["mode"], quote=quote, fill=fill,
                 slip_pct=round(sp, 3), fee_usd=round(fee, 4), usd=round(net, 4), qty=qty, pnl_usd=round(pnl, 4),
                 frac_of_original=round(qty / pos["qty0"], 3), closed=closed, reason=reason,
                 pos_pnl_usd=round(pos["realized_usd"], 4) if closed else None, agent=agent, mcap=mcap,
                 pnl_pct=round((fill * (1 - config.FEE_PCT_PER_SIDE / 100) / pos["entry_fill"] - 1) * 100, 2))
    import messages, notify
    notify.push(messages.sell_alert(store.read_ledger()[-1]), title="Trading Desk · PAPER sell")
    store.log("executor", f"PAPER SELL {pos['symbol']} {qty / pos['qty0'] * 100:.0f}% @ {fill:.8g} net ${net:.2f} pnl ${pnl:+.2f} - {reason}")
    if closed:
        del state["positions"][mint]
    return pnl


def mark_value(pos, quote, liq):
    v = pos["qty"] * quote
    return v * (1 - slip_pct(v, liq) / 100) * (1 - config.FEE_PCT_PER_SIDE / 100)
