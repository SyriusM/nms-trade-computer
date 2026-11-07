"""Turn a deobfuscated save into the few facts a trader needs."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .gamedata import Address, good


def _u32(v) -> int:
    """Units/nanites are stored as signed int32 but mean unsigned."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return v + (1 << 32) if v < 0 else v


def player_state(root: dict) -> dict:
    """PlayerStateData of the active context (base game or expedition)."""
    if "PlayerStateData" in root and isinstance(root["PlayerStateData"], dict):
        return root["PlayerStateData"]
    active = str(root.get("ActiveContext", "")).lower()
    order = ["ExpeditionContext", "BaseContext"] if active.startswith("season") else \
        ["BaseContext", "ExpeditionContext"]
    for ctx in order:
        psd = (root.get(ctx) or {}).get("PlayerStateData")
        if isinstance(psd, dict):
            return psd
    raise KeyError("PlayerStateData not found in save")


def parse_address(value, galaxy: int = 0) -> Address | None:
    """Address from a GalacticAddress dict, a UniverseAddress dict or a packed UA.

    Packed form (int or '0x..' string): the low 48 bits are the portal code
    P SSS YY ZZZ XXX, galaxy (reality index) in the bits above.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if "GalacticAddress" in value:
            return parse_address(value["GalacticAddress"], int(value.get("RealityIndex", galaxy) or 0))
        if "VoxelX" in value:
            return Address(galaxy=galaxy, x=int(value.get("VoxelX", 0)), y=int(value.get("VoxelY", 0)),
                           z=int(value.get("VoxelZ", 0)), system=int(value.get("SolarSystemIndex", 0)),
                           planet=int(value.get("PlanetIndex", 0)))
        return None
    if isinstance(value, str):
        s = value.strip()
        try:
            value = int(s, 16) if s.lower().startswith("0x") else int(s)
        except ValueError:
            return None
    if isinstance(value, int):
        code = f"{value & 0xFFFFFFFFFFFF:012X}"
        gal = (value >> 48) & 0xFF
        return Address.from_glyphs(code, galaxy=gal or galaxy)
    return None


@dataclass
class Stack:
    item_id: str
    amount: int
    max_amount: int
    where: str  # "ship" / "exosuit" / "freighter"


@dataclass
class InventoryInfo:
    where: str
    slots_total: int
    slots_used: int
    stacks: list[Stack] = field(default_factory=list)


@dataclass
class MarketRecord:
    """One TradingSupplyData entry: the game's memory of a market you traded in."""
    address: Address | None
    item_id: str
    supply: float | None
    demand: float | None
    timestamp: int | None


@dataclass
class Snapshot:
    path: str
    mtime: float
    save_name: str
    address: Address | None
    units: int
    nanites: int
    quicksilver: int
    inventories: list[InventoryInfo]
    markets: list[MarketRecord]
    system_names: dict[str, str]
    play_time: int

    def trade_goods(self) -> dict[str, int]:
        """Trade goods held anywhere (ship + exosuit + freighter): id -> amount."""
        out: dict[str, int] = {}
        for inv in self.inventories:
            for s in inv.stacks:
                if good(s.item_id):
                    out[s.item_id] = out.get(s.item_id, 0) + s.amount
        return out

    def ship_cargo(self) -> InventoryInfo | None:
        for inv in self.inventories:
            if inv.where == "ship":
                return inv
        return None

    def trade_stack_size(self) -> int | None:
        """Largest MaxAmount seen on a trade-goods slot in the ship (real stack cap)."""
        ship = self.ship_cargo()
        best = None
        if ship:
            for s in ship.stacks:
                if good(s.item_id) and s.max_amount:
                    best = max(best or 0, s.max_amount)
        return best


def _inventory(inv: dict, where: str) -> InventoryInfo | None:
    if not isinstance(inv, dict):
        return None
    slots = inv.get("Slots") or []
    valid = inv.get("ValidSlotIndices") or []
    info = InventoryInfo(where=where, slots_total=len(valid) or len(slots), slots_used=len(slots))
    for s in slots:
        if not isinstance(s, dict):
            continue
        item = str(s.get("Id", "")).lstrip("^")
        if not item:
            continue
        info.stacks.append(Stack(item, int(s.get("Amount", 0) or 0), int(s.get("MaxAmount", 0) or 0), where))
    return info


def _merge(a: InventoryInfo | None, b: InventoryInfo | None) -> InventoryInfo | None:
    if a is None:
        return b
    if b is None:
        return a
    return InventoryInfo(a.where, a.slots_total + b.slots_total, a.slots_used + b.slots_used, a.stacks + b.stacks)


def _markets(psd: dict, galaxy: int) -> list[MarketRecord]:
    out: list[MarketRecord] = []
    for e in psd.get("TradingSupplyData") or []:
        if not isinstance(e, dict):
            continue
        addr = None
        for k, v in e.items():
            if "Address" in k or k in ("UA", "Universe"):
                addr = parse_address(v, galaxy)
                if addr:
                    break
        item = ""
        for k in ("Product", "Id", "Item"):
            if e.get(k):
                item = str(e[k]).lstrip("^")
                break

        def num(k):
            try:
                return float(e[k])
            except (KeyError, TypeError, ValueError):
                return None

        ts = e.get("Timestamp")
        out.append(MarketRecord(addr, item, num("Supply"), num("Demand"),
                                int(ts) if isinstance(ts, (int, float)) else None))
    return out


def _system_names(root: dict) -> dict[str, str]:
    """System names from discovery records (DD.DT == 'SolarSystem', DM.CN)."""
    names: dict[str, str] = {}
    dm = root.get("DiscoveryManagerData") or {}
    store = ((dm.get("DiscoveryData-v1") or {}).get("Store") or {})
    for rec in store.get("Record") or []:
        try:
            dd, meta = rec.get("DD") or {}, rec.get("DM") or {}
            if dd.get("DT") != "SolarSystem":
                continue
            name = meta.get("CN") or ""
            addr = parse_address(dd.get("UA"))
            if addr and name:
                names[addr.key] = str(name)
        except (AttributeError, ValueError):
            continue
    return names


def snapshot(root: dict, path: str | Path = "", mtime: float | None = None) -> Snapshot:
    psd = player_state(root)
    ua = psd.get("UniverseAddress") or {}
    galaxy = int(ua.get("RealityIndex", 0) or 0) if isinstance(ua, dict) else 0
    address = parse_address(ua, galaxy)

    invs: list[InventoryInfo] = []
    suit = _merge(_inventory(psd.get("Inventory"), "exosuit"), _inventory(psd.get("Inventory_Cargo"), "exosuit"))
    if suit:
        invs.append(suit)
    ships = psd.get("ShipOwnership") or []
    idx = int(psd.get("PrimaryShip", 0) or 0)
    if isinstance(ships, list) and 0 <= idx < len(ships) and isinstance(ships[idx], dict):
        ship = _merge(_inventory(ships[idx].get("Inventory"), "ship"),
                      _inventory(ships[idx].get("Inventory_Cargo"), "ship"))
        if ship:
            invs.append(ship)
    frt = _merge(_inventory(psd.get("FreighterInventory"), "freighter"),
                 _inventory(psd.get("FreighterInventory_Cargo"), "freighter"))
    if frt:
        invs.append(frt)

    names = {}
    for ctx in (root, root.get("BaseContext") or {}, root.get("ExpeditionContext") or {}, psd):
        if isinstance(ctx, dict):
            names.update(_system_names(ctx))

    common = root.get("CommonStateData") or {}
    return Snapshot(
        path=str(path), mtime=mtime if mtime is not None else time.time(),
        save_name=str(common.get("SaveName") or psd.get("SaveName") or ""),
        address=address, units=_u32(psd.get("Units")), nanites=_u32(psd.get("Nanites")),
        quicksilver=_u32(psd.get("Specials")), inventories=invs,
        markets=_markets(psd, galaxy), system_names=names,
        play_time=int(common.get("TotalPlayTime") or psd.get("TotalPlayTime") or 0),
    )


def read_snapshot(path: str | Path) -> Snapshot:
    from .savefile import load_save
    p = Path(path)
    return snapshot(load_save(p), p, p.stat().st_mtime)
