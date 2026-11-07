"""Build realistic test saves: obfuscated keys + 0xFEEDA1E5 LZ4 chunks."""
from __future__ import annotations

import json
import struct

from nmstrade.savefile import MAGIC, load_mapping


def lz4_literals_block(data: bytes) -> bytes:
    """Valid LZ4 block made of one literal-only sequence."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    out = bytearray([0xF0])
    rest = n - 15
    while rest >= 255:
        out.append(255)
        rest -= 255
    out.append(rest)
    return bytes(out) + data


def compress(data: bytes, chunk: int = 0x80000) -> bytes:
    out = bytearray()
    for i in range(0, len(data), chunk):
        piece = data[i:i + chunk]
        block = lz4_literals_block(piece)
        out += struct.pack("<4I", MAGIC, len(block), len(piece), 0) + block
    return bytes(out)


def obfuscate(obj, rev: dict):
    if isinstance(obj, dict):
        return {rev.get(k, k): obfuscate(v, rev) for k, v in obj.items()}
    if isinstance(obj, list):
        return [obfuscate(v, rev) for v in obj]
    return obj


def slot(item: str, amount: int, max_amount: int = 50, x: int = 0, y: int = 0) -> dict:
    return {"Type": {"InventoryType": "Product"}, "Id": "^" + item, "Amount": amount,
            "MaxAmount": max_amount, "Index": {"X": x, "Y": y}}


def make_save(*, x=100, y=-5, z=-300, system=0x7A, planet=1, galaxy=0, units=1_000_000,
              nanites=500, ship_slots=None, suit_slots=None, markets=None, names=None) -> dict:
    psd = {
        "UniverseAddress": {"RealityIndex": galaxy, "GalacticAddress": {
            "VoxelX": x, "VoxelY": y, "VoxelZ": z, "SolarSystemIndex": system, "PlanetIndex": planet}},
        "Units": units if units < 2**31 else units - 2**32,
        "Nanites": nanites, "Specials": 42,
        "Inventory": {"Slots": suit_slots or [], "ValidSlotIndices": [{"X": i, "Y": 0} for i in range(20)]},
        "PrimaryShip": 0,
        "ShipOwnership": [{"Inventory": {"Slots": ship_slots or [],
                                         "ValidSlotIndices": [{"X": i, "Y": 0} for i in range(30)]}}],
        "TradingSupplyData": markets or [],
    }
    root = {"Version": 4720, "ActiveContext": "Main",
            "CommonStateData": {"SaveName": "Test", "TotalPlayTime": 3600},
            "BaseContext": {"GameMode": 1, "PlayerStateData": psd}}
    if names:
        root["DiscoveryManagerData"] = {"DiscoveryData-v1": {"Store": {"Record": [
            {"DD": {"UA": ua, "DT": "SolarSystem"}, "DM": {"CN": n}} for ua, n in names]}}}
    return root


def write_save(path, root: dict, plain: bool = False) -> None:
    rev = {v: k for k, v in load_mapping().items()}
    text = json.dumps(obfuscate(root, rev), separators=(",", ":")).encode() + b"\x00"
    path.write_bytes(text if plain else compress(text, chunk=4096))
