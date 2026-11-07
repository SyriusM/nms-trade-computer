"""Read-only access to No Man's Sky PC save files (save.hg, save2.hg, ...).

Format (community-documented, see NMSCD/NMS-Save-Decoder):
    repeat until EOF:
        uint32 LE magic 0xFEEDA1E5
        uint32 LE compressed size
        uint32 LE uncompressed size
        uint32 LE padding
        LZ4 block
Some saves are plain JSON (start with '{"'). JSON keys are obfuscated
3-character codes; data/mapping.json (MBINCompiler release asset) maps them
to readable names.

The game is never touched: files are only read.
"""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

MAGIC = 0xFEEDA1E5
MAPPING_PATH = Path(__file__).with_name("data") / "mapping.json"
STEAM_APP_ID = "275850"

try:  # optional fast path
    import lz4.block as _lz4  # type: ignore
except Exception:  # pragma: no cover - depends on environment
    _lz4 = None


class SaveFormatError(ValueError):
    pass


def lz4_block_decompress(src: bytes, out_size: int) -> bytes:
    """Pure-Python LZ4 block decoder (no frame header)."""
    if _lz4 is not None:
        return _lz4.decompress(src, uncompressed_size=out_size)
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if off == 0:
            raise SaveFormatError("LZ4: zero offset")
        mlen = token & 15
        if mlen == 15:
            while True:
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4
        start = len(out) - off
        if start < 0:
            raise SaveFormatError("LZ4: offset before start of output")
        if off >= mlen:
            out += out[start:start + mlen]
        else:
            for k in range(mlen):
                out.append(out[start + k])
    if len(out) != out_size:
        raise SaveFormatError(f"LZ4: expected {out_size} bytes, got {len(out)}")
    return bytes(out)


def decompress(raw: bytes) -> bytes:
    if len(raw) < 4:
        raise SaveFormatError("file too small")
    if raw[:1] == b"{":
        return raw.rstrip(b"\x00")
    if struct.unpack_from("<I", raw)[0] != MAGIC:
        raise SaveFormatError("not a No Man's Sky save (bad magic)")
    out, pos = bytearray(), 0
    while pos < len(raw):
        if pos + 16 > len(raw):
            raise SaveFormatError("truncated chunk header")
        magic, csize, usize, _ = struct.unpack_from("<4I", raw, pos)
        if magic != MAGIC:
            raise SaveFormatError(f"bad chunk at offset {pos}")
        pos += 16
        block = raw[pos:pos + csize]
        if len(block) != csize:
            raise SaveFormatError("truncated chunk")
        out += lz4_block_decompress(block, usize)
        pos += csize
    return bytes(out).rstrip(b"\x00")


_mapping_cache: dict | None = None


def load_mapping(path: Path = MAPPING_PATH) -> dict:
    global _mapping_cache
    if _mapping_cache is None or path != MAPPING_PATH:
        data = json.loads(path.read_text(encoding="utf-8"))
        mp = {m["Key"]: m["Value"] for m in data["Mapping"]}
        if path != MAPPING_PATH:
            return mp
        _mapping_cache = mp
    return _mapping_cache


def deobfuscate(obj, mp: dict):
    if isinstance(obj, dict):
        return {mp.get(k, k): deobfuscate(v, mp) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deobfuscate(v, mp) for v in obj]
    return obj


def load_save(path: os.PathLike | str) -> dict:
    """Read, decompress and deobfuscate one save file."""
    raw = Path(path).read_bytes()
    text = decompress(raw).decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SaveFormatError(f"save JSON is broken: {e}") from e
    return deobfuscate(data, load_mapping())


# ---------------------------------------------------------------- locations

def candidate_save_roots() -> list[Path]:
    """Folders that may hold HelloGames/NMS on Linux (Proton) and Windows."""
    home = Path.home()
    roots: list[Path] = []
    env = os.environ.get("NMS_SAVE_DIR")
    if env:
        roots.append(Path(env))
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "HelloGames" / "NMS")
    steam_dirs = [
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]
    libs: list[Path] = []
    for sd in steam_dirs:
        libs.append(sd)
        vdf = sd / "steamapps" / "libraryfolders.vdf"
        try:
            for line in vdf.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith('"path"'):
                    libs.append(Path(line.split('"')[3]))
        except OSError:
            pass
    for lib in libs:
        roots.append(lib / "steamapps" / "compatdata" / STEAM_APP_ID / "pfx" / "drive_c"
                     / "users" / "steamuser" / "AppData" / "Roaming" / "HelloGames" / "NMS")
    seen, out = set(), []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def find_save_files(root: Path | None = None) -> list[Path]:
    """All save*.hg files (not mf_*.hg metadata), newest first."""
    roots = [root] if root else candidate_save_roots()
    files: list[Path] = []
    for r in roots:
        if not r or not r.is_dir():
            continue
        for p in r.rglob("save*.hg"):
            if p.name.startswith("mf_"):
                continue
            files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def newest_save(root: Path | None = None) -> Path | None:
    files = find_save_files(root)
    return files[0] if files else None
