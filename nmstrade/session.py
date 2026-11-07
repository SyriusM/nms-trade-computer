"""Detect buys and sells by comparing consecutive save snapshots.

The game saves on its own (autosave when you leave the station, warp, land...)
and when you save manually. Between two saves in the same system, a drop in a
trade good plus a rise in units is a sale; the opposite is a buy. When several
goods change at once the unit change is split by base value.
"""
from __future__ import annotations

from dataclasses import dataclass

from .gamedata import good
from .playerstate import Snapshot
from .store import Store, Trade


@dataclass
class SessionStats:
    profit: int = 0
    sold_units: int = 0
    spent: int = 0
    trades: int = 0
    start_units: int | None = None
    start_time: float | None = None


def detect_trades(prev: Snapshot, cur: Snapshot, store: Store) -> list[Trade]:
    if not prev.address or not cur.address or prev.address.key != cur.address.key:
        return []
    a, b = prev.trade_goods(), cur.trade_goods()
    delta = {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b)}
    delta = {k: v for k, v in delta.items() if v}
    if not delta:
        return []
    du = cur.units - prev.units
    sold = {k: -v for k, v in delta.items() if v < 0}
    bought = {k: v for k, v in delta.items() if v > 0}
    sysrec = store.systems.get(cur.address.key)
    econ = sysrec.economy if sysrec else ""
    wealth = sysrec.wealth if sysrec else ""
    out: list[Trade] = []

    def split(items: dict[str, int], total: float, kind: str):
        weight = sum(good(k).base * q for k, q in items.items() if good(k))
        if weight <= 0 or total <= 0:
            return
        for k, q in items.items():
            g = good(k)
            if not g:
                continue
            share = total * (g.base * q) / weight
            out.append(Trade(cur.mtime, kind, k, q, share / q, cur.address.key, econ, wealth))

    if sold and not bought and du > 0:
        split(sold, du, "sell")
    elif bought and not sold and du < 0:
        split(bought, -du, "buy")
    # mixed buy+sell between two saves: prices cannot be separated reliably -> skip
    return out


def update_stats(stats: SessionStats, snap: Snapshot, trades: list[Trade]) -> None:
    if stats.start_units is None:
        stats.start_units = snap.units
        stats.start_time = snap.mtime
    for t in trades:
        stats.trades += 1
        if t.kind == "sell":
            stats.sold_units += t.qty
            stats.profit += int(t.unit_price * t.qty)
        else:
            stats.spent += int(t.unit_price * t.qty)
            stats.profit -= int(t.unit_price * t.qty)
