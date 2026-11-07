"""Static game facts: trade goods, economy types, wealth levels, addresses.

Names and values come from data/gamedata.json, extracted from game data dumps.
What each economy *sells* is game data (GcTradingClassTable "Sells"): every
economy type sells its own trade-goods category. What each economy *needs* is
not in any public dump available to this project, so the app learns it from
the player (demand table, see demand.py) instead of guessing.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

_DATA = json.loads((Path(__file__).with_name("data") / "gamedata.json").read_text(encoding="utf-8"))

# Economy keys follow the game's localisation keys (UI_ECON_CLASS_<KEY>_n).
ECONOMIES = ["TRADE", "ALLOY", "SCIENCE", "MINING", "TECH", "MANUFACT", "POWER"]
PIRATE = "PIRATE"

# GcTradingClassTable order: Mining, HighTech, Trading, Manufacturing, Fusion,
# Scientific, PowerGeneration -> Sells: Mineral, Tech, Commodity, Component,
# Alloy, Exotic, Energy.
SELLS = {
    "MINING": "Mineral",
    "TECH": "Tech",
    "TRADE": "Commodity",
    "MANUFACT": "Component",
    "ALLOY": "Alloy",
    "SCIENCE": "Exotic",
    "POWER": "Energy",
    PIRATE: "Smuggled",
}
CATEGORY_ECONOMY = {v: k for k, v in SELLS.items()}

ECONOMY_NAMES: dict[str, list[str]] = dict(_DATA["economy_names"])
ECONOMY_NAMES_PL: dict[str, list[str]] = dict(_DATA.get("economy_names_pl", {}))
ECONOMY_NAMES[PIRATE] = [_DATA["pirate"]["economy"]]
WEALTH_NAMES: dict[str, list[str]] = dict(_DATA["wealth_names"])
CONFLICT_NAMES: dict[str, list[str]] = dict(_DATA["conflict_names"])
CONFLICT_NAMES[PIRATE] = [_DATA["pirate"]["conflict"]]

WEALTH_LEVELS = ["LOW", "MED", "HIGH"]
WEALTH_STARS = {"LOW": "★", "MED": "★★", "HIGH": "★★★", PIRATE: "☠"}
CONFLICT_LEVELS = ["LOW", "MED", "HIGH", PIRATE]

# Short Polish labels used by the app's own UI (game names stay in English).
ECONOMY_LABEL = {
    "TRADE": "Handel", "ALLOY": "Mat. zaawansowane", "SCIENCE": "Naukowa",
    "MINING": "Wydobycie", "TECH": "Wysoka technologia", "MANUFACT": "Produkcja",
    "POWER": "Energia", PIRATE: "Piraci (czarny rynek)",
}
CATEGORY_LABEL = {
    "Commodity": "Handel", "Alloy": "Materiały", "Exotic": "Naukowe",
    "Mineral": "Minerały", "Tech": "Technologia", "Component": "Części",
    "Energy": "Energia", "Smuggled": "Przemyt",
}
WEALTH_LABEL = {"LOW": "biedny", "MED": "średni", "HIGH": "bogaty", PIRATE: "piracki"}


@dataclass(frozen=True)
class Good:
    id: str
    name: str
    category: str
    base: int
    tier: int
    buy_markup: float
    stack: int

    @property
    def economy(self) -> str:
        return CATEGORY_ECONOMY.get(self.category, "")


def _load_goods() -> dict[str, Good]:
    out: dict[str, Good] = {}
    for g in _DATA["goods"]:
        gid = g["id"]
        digits = "".join(ch for ch in gid if ch.isdigit())
        out[gid] = Good(gid, g["name"], g["category"], int(g["base"]),
                        int(digits or 1), float(g["buy_markup"]), int(g["stack"]))
    return out


GOODS: dict[str, Good] = _load_goods()


def good(item_id: str) -> Good | None:
    return GOODS.get(item_id.lstrip("^"))


def goods_of(category: str) -> list[Good]:
    return sorted((g for g in GOODS.values() if g.category == category), key=lambda g: g.base)


# ------------------------------------------------------------ name lookups

def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").split())


def economy_from_name(name: str) -> str | None:
    """'Ore Extraction' -> 'MINING'. Accepts game names (EN/PL), keys and app labels."""
    n = _norm(name)
    if not n:
        return None
    for key in list(ECONOMY_NAMES) :
        names = ECONOMY_NAMES[key] + ECONOMY_NAMES_PL.get(key, []) + [key, ECONOMY_LABEL[key]]
        if any(_norm(x) == n for x in names):
            return key
    return None


def wealth_from_name(name: str) -> str | None:
    n = _norm(name)
    if not n:
        return None
    if n in ("black market", "pirate", "piraci"):
        return PIRATE
    stars = n.count("★")
    if stars:
        return WEALTH_LEVELS[min(stars, 3) - 1]
    for key, names in WEALTH_NAMES.items():
        if any(_norm(x) == n for x in names + [key, WEALTH_LABEL[key]]):
            return key
    return None


def conflict_from_name(name: str) -> str | None:
    n = _norm(name)
    if not n:
        return None
    for key, names in CONFLICT_NAMES.items():
        if any(_norm(x) == n for x in names + [key]):
            return key
    return None


def all_economy_names() -> list[str]:
    out = []
    for key in ECONOMIES + [PIRATE]:
        out += ECONOMY_NAMES[key] + ECONOMY_NAMES_PL.get(key, [])
    return out


def all_wealth_names() -> list[str]:
    out = []
    for key in WEALTH_LEVELS:
        out += WEALTH_NAMES[key]
    return out + ECONOMY_NAMES[PIRATE]


def all_conflict_names() -> list[str]:
    out = []
    for key in CONFLICT_LEVELS:
        out += CONFLICT_NAMES[key]
    return out


# ------------------------------------------------------------ addresses

GALAXIES = ["Euclid", "Hilbert Dimension", "Calypso", "Hesperius Dimension", "Hyades",
            "Ickjamatew", "Budullangr", "Kikolgallr", "Eltiensleem", "Eissentam"]


def galaxy_name(index: int) -> str:
    if 0 <= index < len(GALAXIES):
        return GALAXIES[index]
    return f"Galaktyka {index + 1}"


@dataclass(frozen=True)
class Address:
    """Galactic address of a star system (planet ignored for trading)."""
    galaxy: int
    x: int  # VoxelX, -2048..2047
    y: int  # VoxelY, -128..127
    z: int  # VoxelZ, -2048..2047
    system: int  # SolarSystemIndex
    planet: int = 0

    @property
    def key(self) -> str:
        """Stable id of the system: galaxy + portal code without planet."""
        return f"{self.galaxy}:{self.glyphs(planet=False)}"

    def glyphs(self, planet: bool = True) -> str:
        """Portal address: P SSS YY ZZZ XXX (12 hex digits, two's complement)."""
        p = (self.planet & 0xF) if planet else 0
        return (f"{p:01X}{self.system & 0xFFF:03X}{self.y & 0xFF:02X}"
                f"{self.z & 0xFFF:03X}{self.x & 0xFFF:03X}")

    def signal_booster(self) -> str:
        """Signal-booster / galactic coordinates XXXX:YYYY:ZZZZ:SSSS."""
        return (f"{(self.x + 0x7FF) & 0xFFFF:04X}:{(self.y + 0x7F) & 0xFFFF:04X}:"
                f"{(self.z + 0x7FF) & 0xFFFF:04X}:{self.system & 0xFFFF:04X}")

    @classmethod
    def from_glyphs(cls, code: str, galaxy: int = 0) -> "Address":
        c = "".join(ch for ch in code if ch.strip()).upper()
        if len(c) != 12 or any(ch not in "0123456789ABCDEF" for ch in c):
            raise ValueError("portal code must be 12 hex digits")

        def signed(v: int, bits: int) -> int:
            return v - (1 << bits) if v >= (1 << (bits - 1)) else v

        return cls(galaxy=galaxy, planet=int(c[0], 16), system=int(c[1:4], 16),
                   y=signed(int(c[4:6], 16), 8), z=signed(int(c[6:9], 16), 12),
                   x=signed(int(c[9:12], 16), 12))


LY_PER_REGION = 400.0


def distance_ly(a: Address, b: Address) -> float:
    """Approximate distance; systems in one region are ~0 ly apart (shown as < 400)."""
    if a.galaxy != b.galaxy:
        return math.inf
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) * LY_PER_REGION


def same_region(a: Address, b: Address) -> bool:
    return a.galaxy == b.galaxy and (a.x, a.y, a.z) == (b.x, b.y, b.z)
