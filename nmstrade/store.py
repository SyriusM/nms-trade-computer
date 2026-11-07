"""Local, persistent knowledge: systems you have seen, what economies need,
and every buy/sell the app detected. Plain JSON in ~/.config/nms-trade-computer/.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .gamedata import ECONOMIES, PIRATE, SELLS, Address, good


def config_dir() -> Path:
    base = os.environ.get("NMS_TRADE_CONFIG") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) if os.environ.get("NMS_TRADE_CONFIG") else Path(base) / "nms-trade-computer"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _atomic_write(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


@dataclass
class System:
    key: str
    galaxy: int
    x: int
    y: int
    z: int
    system: int
    name: str = ""
    economy: str = ""     # ECONOMIES key or PIRATE, "" = unknown
    wealth: str = ""      # LOW / MED / HIGH / PIRATE
    conflict: str = ""    # LOW / MED / HIGH / PIRATE
    notes: str = ""
    first_seen: float = 0.0
    last_seen: float = 0.0
    visits: int = 0

    @property
    def address(self) -> Address:
        return Address(self.galaxy, self.x, self.y, self.z, self.system)

    @property
    def glyphs(self) -> str:
        return self.address.glyphs()

    @property
    def known(self) -> bool:
        return bool(self.economy)

    def label(self) -> str:
        return self.name or self.glyphs


@dataclass
class Trade:
    ts: float
    kind: str          # "buy" / "sell"
    item_id: str
    qty: int
    unit_price: float  # units per item
    system_key: str
    economy: str
    wealth: str

    @property
    def ratio(self) -> float:
        g = good(self.item_id)
        return self.unit_price / g.base if g and g.base else 0.0


@dataclass
class Settings:
    cargo_capacity: int = 0        # trade goods per run; 0 = from save
    stock_per_good: int = 30       # how many of one good a station sells you (estimate)
    jump_range_ly: float = 1500.0
    minutes_per_jump: float = 1.5
    minutes_per_stop: float = 4.0
    use_teleporter: bool = True    # visited stations are one teleport away
    minutes_teleport: float = 2.5
    demand_bonus: float = 1.70     # sell ratio where the economy needs the goods (estimate)
    local_sell_ratio: float = 0.80 # selling goods back to the economy that makes them
    other_sell_ratio: float = 1.00
    local_buy_ratio: float = 0.88  # buying local goods (base +10% markup, local discount)
    wealth_factor: dict = field(default_factory=lambda: {"LOW": 0.95, "MED": 1.0, "HIGH": 1.05, PIRATE: 1.0})
    learn_min_ratio: float = 1.30  # sale this far above base value marks a "need"
    skip_high_conflict: bool = False
    copy_glyphs: bool = True
    save_dir: str = ""
    poll_seconds: float = 2.0
    always_on_top: bool = False
    alpha: float = 0.97


class Store:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or config_dir()
        self.systems: dict[str, System] = {}
        self.needs: dict[str, dict] = {}   # economy -> {"category": str, "source": "user"|"learned"}
        self.trades: list[Trade] = []
        self.settings = Settings()
        self.load()

    # ---------------------------------------------------------- persistence
    def load(self) -> None:
        for d in _read(self.folder / "systems.json", []):
            try:
                s = System(**d)
                self.systems[s.key] = s
            except TypeError:
                continue
        self.needs = _read(self.folder / "demand.json", {})
        self.trades = []
        for d in _read(self.folder / "trades.json", []):
            try:
                self.trades.append(Trade(**d))
            except TypeError:
                continue
        raw = _read(self.folder / "settings.json", {})
        base = asdict(Settings())
        base.update({k: v for k, v in raw.items() if k in base})
        self.settings = Settings(**base)

    def save(self) -> None:
        _atomic_write(self.folder / "systems.json", [asdict(s) for s in self.systems.values()])
        _atomic_write(self.folder / "demand.json", self.needs)
        _atomic_write(self.folder / "trades.json", [asdict(t) for t in self.trades])
        _atomic_write(self.folder / "settings.json", asdict(self.settings))

    # ---------------------------------------------------------- systems
    def touch(self, addr: Address, name: str = "") -> System:
        """Register a visit to a system (creates it on first sight)."""
        now = time.time()
        s = self.systems.get(addr.key)
        if s is None:
            s = System(addr.key, addr.galaxy, addr.x, addr.y, addr.z, addr.system, first_seen=now)
            self.systems[s.key] = s
        if name and not s.name:
            s.name = name
        if now - s.last_seen > 60:
            s.visits += 1
        s.last_seen = now
        return s

    def add_manual(self, glyphs: str, galaxy: int, name: str = "", economy: str = "",
                   wealth: str = "", conflict: str = "") -> System:
        addr = Address.from_glyphs(glyphs, galaxy)
        addr = Address(addr.galaxy, addr.x, addr.y, addr.z, addr.system)
        s = self.systems.get(addr.key) or System(addr.key, addr.galaxy, addr.x, addr.y, addr.z,
                                                   addr.system, first_seen=time.time())
        s.name = name or s.name
        s.economy = economy or s.economy
        s.wealth = wealth or s.wealth
        s.conflict = conflict or s.conflict
        self.systems[s.key] = s
        return s

    def remove(self, key: str) -> None:
        self.systems.pop(key, None)

    # ---------------------------------------------------------- demand table
    def need_of(self, economy: str) -> str | None:
        e = self.needs.get(economy)
        return e.get("category") if e else None

    def set_need(self, economy: str, category: str | None, source: str = "user") -> None:
        if not category:
            self.needs.pop(economy, None)
        else:
            self.needs[economy] = {"category": category, "source": source}

    def learned_needs(self) -> dict[str, tuple[str, float, int]]:
        """From your own sales: economy -> (category, median sell ratio, sales)."""
        by: dict[tuple[str, str], list[float]] = {}
        for t in self.trades:
            g = good(t.item_id)
            if t.kind != "sell" or not g or not t.economy or t.economy == PIRATE:
                continue
            if g.category == SELLS.get(t.economy):
                continue
            by.setdefault((t.economy, g.category), []).append(t.ratio)
        out: dict[str, tuple[str, float, int]] = {}
        for (econ, cat), ratios in by.items():
            med = statistics.median(ratios)
            if med < self.settings.learn_min_ratio:
                continue
            if econ not in out or med > out[econ][1]:
                out[econ] = (cat, med, len(ratios))
        return out

    def apply_learned(self) -> list[str]:
        """Fill demand entries the player has not set by hand. Returns changed economies."""
        changed = []
        for econ, (cat, _med, _n) in self.learned_needs().items():
            cur = self.needs.get(econ)
            if cur and cur.get("source") == "user":
                continue
            if not cur or cur.get("category") != cat:
                self.set_need(econ, cat, "learned")
                changed.append(econ)
        return changed

    def demand_complete(self) -> bool:
        return all(self.need_of(e) for e in ECONOMIES)

    # ---------------------------------------------------------- trades
    def record(self, trade: Trade) -> None:
        self.trades.append(trade)

    def observed_ratio(self, kind: str, economy: str, category: str, wealth: str = "") -> tuple[float, int] | None:
        """Median price/base ratio you actually got, same wealth preferred."""
        pool = [t for t in self.trades if t.kind == kind and t.economy == economy
                and (g := good(t.item_id)) and g.category == category]
        same = [t for t in pool if wealth and t.wealth == wealth]
        use = same if len(same) >= 1 else pool
        if not use:
            return None
        return statistics.median(t.ratio for t in use), len(use)

    def last_buy_price(self, item_id: str) -> float | None:
        for t in reversed(self.trades):
            if t.kind == "buy" and t.item_id == item_id:
                return t.unit_price
        return None
