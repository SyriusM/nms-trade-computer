"""Trade advice: what to buy here, where to sell it, what to do with your hold.

Prices are estimated as ratios of each good's base value. Your own recorded
trades always win over the built-in estimates (see Store.observed_ratio).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .gamedata import PIRATE, SELLS, Good, distance_ly, goods_of, good
from .store import Store, System


@dataclass
class Estimate:
    ratio: float
    source: str  # "twoje" (your trades), "popyt" (demand table), "szac." (estimate)


def sell_estimate(store: Store, dest: System, g: Good) -> Estimate:
    st = store.settings
    wf = st.wealth_factor.get(dest.wealth, 1.0)
    obs = store.observed_ratio("sell", dest.economy, g.category, dest.wealth)
    if obs:
        return Estimate(obs[0], "twoje")
    if g.category == "Smuggled":
        if dest.economy == PIRATE or not dest.economy:
            return Estimate(0.0, "szac.")
        return Estimate(st.other_sell_ratio * wf, "szac.")
    if dest.economy == PIRATE:
        return Estimate(st.other_sell_ratio, "szac.")
    if g.category == SELLS.get(dest.economy):
        return Estimate(st.local_sell_ratio * wf, "szac.")
    if store.need_of(dest.economy) == g.category:
        return Estimate(st.demand_bonus * wf, "popyt")
    return Estimate(st.other_sell_ratio * wf, "szac.")


def buy_estimate(store: Store, here: System, g: Good) -> Estimate:
    obs = store.observed_ratio("buy", here.economy, g.category, here.wealth)
    if obs:
        return Estimate(obs[0], "twoje")
    wf = store.settings.wealth_factor.get(here.wealth, 1.0)
    # richer systems sell their own goods cheaper: invert the wealth factor
    return Estimate(store.settings.local_buy_ratio / wf, "szac.")


def travel_minutes(store: Store, a: System, b: System) -> tuple[float, int, float]:
    d = distance_ly(a.address, b.address)
    if math.isinf(d):
        return math.inf, 0, d
    st = store.settings
    if st.use_teleporter and a.visits > 0 and b.visits > 0:
        return st.minutes_per_stop + st.minutes_teleport, 0, d  # 0 jumps = station teleporter
    jumps = max(1, math.ceil(d / max(st.jump_range_ly, 1.0)))
    return st.minutes_per_stop + jumps * st.minutes_per_jump, jumps, d


def capacity(store: Store, snap_capacity: int | None) -> int:
    if store.settings.cargo_capacity > 0:
        return store.settings.cargo_capacity
    return snap_capacity or 50


@dataclass
class Lot:
    good: Good
    qty: int
    buy_price: float
    sell_price: float

    @property
    def profit(self) -> float:
        return (self.sell_price - self.buy_price) * self.qty


@dataclass
class Leg:
    origin: System
    dest: System
    good: Good
    buy_price: float
    sell_price: float
    qty: int
    minutes: float
    jumps: int
    distance: float
    sources: str
    lots: list = None  # list[Lot]: best tier first, lower tiers fill the rest of the hold

    @property
    def unit_profit(self) -> float:
        return self.sell_price - self.buy_price

    @property
    def profit(self) -> float:
        if self.lots:
            return sum(lot.profit for lot in self.lots)
        return self.unit_profit * self.qty

    @property
    def per_hour(self) -> float:
        return self.profit / self.minutes * 60 if self.minutes > 0 else 0.0


def candidates(store: Store, here: System) -> list[System]:
    out = []
    for s in store.systems.values():
        if s.key == here.key or s.galaxy != here.galaxy or not s.economy:
            continue
        if store.settings.skip_high_conflict and s.conflict in ("HIGH", PIRATE) and s.economy != PIRATE:
            continue
        out.append(s)
    return out


def best_leg(store: Store, here: System, dest: System, qty: int) -> Leg | None:
    if not here.economy:
        return None
    cat = SELLS.get(here.economy)
    if not cat:
        return None
    minutes, jumps, dist = travel_minutes(store, here, dest)
    if math.isinf(minutes):
        return None
    stock = store.settings.stock_per_good or qty
    lots: list[Lot] = []
    sources = ""
    left = qty
    priced = []
    for g in goods_of(cat):
        b = buy_estimate(store, here, g)
        s = sell_estimate(store, dest, g)
        if s.ratio <= 0:
            continue
        priced.append((Lot(g, 0, g.base * b.ratio, g.base * s.ratio), f"{b.source}/{s.source}"))
    priced.sort(key=lambda p: p[0].sell_price - p[0].buy_price, reverse=True)
    for lot, src in priced:
        if left <= 0 or lot.sell_price <= lot.buy_price:
            break
        lot.qty = min(stock, left)
        left -= lot.qty
        lots.append(lot)
        sources = sources or src
    if not lots:
        return None
    top = lots[0]
    return Leg(here, dest, top.good, top.buy_price, top.sell_price, qty - left, minutes, jumps, dist,
               sources, lots)


def opportunities(store: Store, here: System, qty: int, limit: int = 15) -> list[Leg]:
    legs = [leg for d in candidates(store, here) if (leg := best_leg(store, here, d, qty))]
    legs = [leg for leg in legs if leg.profit > 0]
    legs.sort(key=lambda leg: leg.per_hour, reverse=True)
    return legs[:limit]


def loop_route(store: Store, here: System, qty: int, hops: int = 4) -> list[Leg]:
    """Greedy chain: best cr/h leg from each stop, never revisiting a system."""
    route: list[Leg] = []
    visited = {here.key}
    cur = here
    for _ in range(hops):
        opts = [leg for leg in opportunities(store, cur, qty, limit=50) if leg.dest.key not in visited]
        if not opts:
            break
        leg = opts[0]
        route.append(leg)
        visited.add(leg.dest.key)
        cur = leg.dest
    return route


@dataclass
class HoldAdvice:
    good: Good
    qty: int
    verdict: str           # "SELL_HERE" / "SELL_THERE" / "HOLD"
    here_price: float
    best: System | None
    best_price: float
    paid: float | None
    note: str


def hold_advice(store: Store, here: System | None, held: dict[str, int]) -> list[HoldAdvice]:
    out: list[HoldAdvice] = []
    for item_id, qty in sorted(held.items()):
        g = good(item_id)
        if not g or qty <= 0:
            continue
        paid = store.last_buy_price(item_id)
        here_price = g.base * sell_estimate(store, here, g).ratio if here and here.economy else 0.0
        best, best_price = None, 0.0
        if here:
            for s in candidates(store, here):
                p = g.base * sell_estimate(store, s, g).ratio
                if p > best_price:
                    best, best_price = s, p
        if here_price and here_price >= best_price * 0.97:
            verdict, note = "SELL_HERE", "tu płacą najlepiej ze znanych systemów"
        elif best and best_price > here_price:
            verdict, note = "SELL_THERE", f"+{best_price - here_price:,.0f} u/szt. vs tutaj".replace(",", " ")
        else:
            verdict, note = "HOLD", "brak lepszego kupca w bazie"
        if paid and max(here_price, best_price) < paid and verdict != "HOLD":
            verdict, note = "HOLD", f"kupione po {paid:,.0f} u – sprzedaż ze stratą".replace(",", " ")
        out.append(HoldAdvice(g, qty, verdict, here_price, best, best_price, paid, note))
    return out
