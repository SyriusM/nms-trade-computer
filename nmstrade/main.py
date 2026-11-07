"""Entry point: python -m nmstrade.main"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path


def _demo(store) -> "object":
    """Fill a throw-away store with sample systems and a fake snapshot."""
    from .gamedata import Address
    from .playerstate import InventoryInfo, MarketRecord, Snapshot, Stack
    from .store import Trade

    now = time.time()
    sample = [
        (Address(0, 412, -3, -1210, 0x07A, 2), "Okelan-Kepler", "MINING", "HIGH", "LOW"),
        (Address(0, 413, -3, -1210, 0x0F1), "Usvarak Prime", "TECH", "HIGH", "LOW"),
        (Address(0, 411, -2, -1209, 0x033), "Ninohi XI", "SCIENCE", "MED", "MED"),
        (Address(0, 415, -4, -1212, 0x1C4), "Ahemb-Iris", "ALLOY", "HIGH", "LOW"),
        (Address(0, 409, -3, -1207, 0x0AA), "Tropaesp", "TRADE", "MED", "LOW"),
        (Address(0, 418, -1, -1215, 0x2B0), "Edsoni Gate", "POWER", "LOW", "HIGH"),
        (Address(0, 420, 0, -1220, 0x045), "Gek Hollow", "PIRATE", "PIRATE", "PIRATE"),
        (Address(0, 414, -3, -1211, 0x12D), "", "", "", ""),
    ]
    for i, (a, name, econ, wealth, conf) in enumerate(sample):
        s = store.touch(a, name)
        s.economy, s.wealth, s.conflict = econ, wealth, conf
        s.last_seen = now - i * 1800
    store.set_need("TECH", "Mineral", "user")
    store.set_need("ALLOY", "Commodity", "learned")
    here = sample[0][0]
    store.record(Trade(now - 5400, "buy", "TRA_MINERALS5", 40, 43800, store.systems[here.key].key, "MINING", "HIGH"))
    store.record(Trade(now - 4800, "sell", "TRA_MINERALS5", 40, 86500,
                       store.systems[sample[1][0].key].key, "TECH", "HIGH"))
    store.record(Trade(now - 3000, "sell", "TRA_COMMODITY4", 25, 52800,
                       store.systems[sample[3][0].key].key, "ALLOY", "HIGH"))
    ship = InventoryInfo("ship", 48, 9, [
        Stack("TRA_MINERALS4", 30, 50, "ship"), Stack("TRA_COMMODITY3", 50, 50, "ship"),
        Stack("TRA_ENERGY5", 12, 50, "ship"), Stack("HYPERFUEL1", 1, 1, "ship")])
    return Snapshot(path="save2.hg", mtime=now, save_name="Demo", address=here, units=48_250_400,
                    nanites=12_870, quicksilver=3_150, inventories=[ship],
                    markets=[MarketRecord(here, "TRA_MINERALS5", -0.3, 0.0, int(now))], system_names={},
                    play_time=360_000)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nmstrade", description="Komputer handlowy do No Man's Sky "
                                 "(czyta zapis gry, niczego w grze nie zmienia).")
    ap.add_argument("--save", type=Path, help="konkretny plik zapisu (save*.hg)")
    ap.add_argument("--save-dir", type=Path, help="folder HelloGames/NMS (domyślnie szuka sam, także w Protonie)")
    ap.add_argument("--demo", action="store_true", help="podgląd na przykładowych danych")
    ap.add_argument("--dump", action="store_true", help="wypisz odczytane dane z zapisu i zakończ")
    ap.add_argument("--list", action="store_true", help="pokaż znalezione pliki zapisów i zakończ")
    args = ap.parse_args(argv)

    from .savefile import find_save_files, newest_save

    if args.list:
        files = find_save_files(args.save_dir)
        for p in files:
            print(time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime)), p)
        if not files:
            print("Nie znaleziono zapisów. Podaj --save-dir.")
        return 0

    if args.dump:
        from .gamedata import good
        from .playerstate import read_snapshot
        path = args.save or newest_save(args.save_dir)
        if not path:
            print("Nie znaleziono zapisu.", file=sys.stderr)
            return 1
        try:
            s = read_snapshot(path)
        except Exception as e:
            print(f"Nie udało się odczytać {path}: {e}", file=sys.stderr)
            return 1
        a = s.address
        print(f"Plik:     {path}")
        print(f"Zapis:    {s.save_name}")
        if a:
            print(f"Glify:    {a.glyphs()}   galaktyka {a.galaxy + 1}   współrzędne {a.signal_booster()}")
        print(f"Jednostki {s.units:,}   nanity {s.nanites:,}   rtęć {s.quicksilver:,}")
        for inv in s.inventories:
            print(f"{inv.where:9s} sloty {inv.slots_used}/{inv.slots_total}")
        for k, v in s.trade_goods().items():
            print(f"  {v:4d} × {good(k).name}")
        print(f"Wpisy rynku (TradingSupplyData): {len(s.markets)}")
        return 0

    import tkinter as tk
    from .gui import App
    from .store import Store

    if args.demo:
        os.environ["NMS_TRADE_CONFIG"] = tempfile.mkdtemp(prefix="nmstrade-demo-")
    store = Store()
    if args.save_dir:
        store.settings.save_dir = str(args.save_dir)
    root = tk.Tk()
    app = App(root, store, save_file=args.save, demo=args.demo)
    if args.demo:
        snap = _demo(store)
        app.here = store.systems[snap.address.key]
        app.snap = snap
        app.stats.start_units, app.stats.start_time, app.stats.profit = snap.units, snap.mtime - 5400, 1_778_000
        app.status.configure(text="TRYB DEMO  ·  przykładowe dane")
        app.render()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
