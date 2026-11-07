import os
import tempfile
import unittest
from pathlib import Path

from nmstrade import gamedata as gd
from nmstrade.gamedata import Address
from nmstrade.playerstate import parse_address, read_snapshot
from nmstrade.savefile import decompress, find_save_files, lz4_block_decompress, newest_save
from nmstrade.session import detect_trades
from nmstrade.store import Store
from nmstrade import planner

from tests.fakesave import compress, make_save, slot, write_save


class TmpDir(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


class TestLZ4(unittest.TestCase):
    def test_match_copy_overlapping(self):
        # literal 'ab' then match offset 2 length 6 -> 'abababab'
        block = bytes([0x22]) + b"ab" + bytes([2, 0])
        self.assertEqual(lz4_block_decompress(block, 8), b"abababab")

    def test_chunks_roundtrip(self):
        data = b'{"a":1}' * 3000 + b"\x00"
        self.assertEqual(decompress(compress(data, chunk=1000)), data.rstrip(b"\x00"))


class TestAddress(unittest.TestCase):
    def test_glyphs_twos_complement(self):
        a = Address(galaxy=0, x=-1, y=-1, z=1, system=0x123, planet=2)
        self.assertEqual(a.glyphs(), "2123FF001FFF")

    def test_roundtrip(self):
        a = Address(galaxy=3, x=-2000, y=100, z=1500, system=0x2F0, planet=4)
        self.assertEqual(Address.from_glyphs(a.glyphs(), 3), a)

    def test_packed_ua(self):
        a = Address(galaxy=0, x=5, y=-3, z=-7, system=0x45, planet=1)
        packed = int(a.glyphs(), 16)
        self.assertEqual(parse_address(hex(packed)), a)
        self.assertEqual(parse_address(packed | (2 << 48)).galaxy, 2)

    def test_signal_booster(self):
        self.assertEqual(Address(0, 0, 0, 0, 0x79).signal_booster(), "07FF:007F:07FF:0079")

    def test_distance(self):
        a, b = Address(0, 0, 0, 0, 1), Address(0, 3, 0, 4, 2)
        self.assertEqual(gd.distance_ly(a, b), 2000.0)


class TestNames(unittest.TestCase):
    def test_economy_aliases(self):
        self.assertEqual(gd.economy_from_name("Ore Extraction"), "MINING")
        self.assertEqual(gd.economy_from_name("nano construction"), "TECH")
        self.assertEqual(gd.economy_from_name("Wydobycie"), "MINING")
        self.assertEqual(gd.economy_from_name("Black Market"), gd.PIRATE)
        self.assertIsNone(gd.economy_from_name("Bananas"))

    def test_wealth(self):
        self.assertEqual(gd.wealth_from_name("Opulent"), "HIGH")
        self.assertEqual(gd.wealth_from_name("Struggling"), "LOW")
        self.assertEqual(gd.wealth_from_name("★★"), "MED")

    def test_goods_table(self):
        self.assertEqual(len(gd.goods_of("Tech")), 5)
        self.assertEqual(gd.good("^TRA_TECH5").base, 50000)
        for e in gd.ECONOMIES:
            self.assertEqual(len(gd.goods_of(gd.SELLS[e])), 5, e)


class TestSave(TmpDir):
    def test_read_compressed_and_plain(self):
        for plain in (False, True):
            p = self.dir / f"save{'p' if plain else ''}.hg"
            write_save(p, make_save(units=3_000_000_000, ship_slots=[slot("TRA_TECH3", 40, 50)],
                                    suit_slots=[slot("FUEL1", 100, 250)]), plain=plain)
            s = read_snapshot(p)
            self.assertEqual(s.units, 3_000_000_000)
            self.assertEqual(s.quicksilver, 42)
            self.assertEqual(s.address.glyphs(), "107AFBED4064")
            self.assertEqual(s.trade_goods(), {"TRA_TECH3": 40})
            self.assertEqual(s.trade_stack_size(), 50)
            self.assertEqual(s.ship_cargo().slots_total, 30)

    def test_markets_and_names(self):
        ua = "0x" + Address(0, 100, -5, -300, 0x7A).glyphs(planet=False)
        p = self.dir / "save.hg"
        write_save(p, make_save(markets=[{"GalacticAddress": ua, "Product": "^TRA_ALLOY2",
                                          "Supply": -0.4, "Demand": 0.2, "Timestamp": 1700000000}],
                                names=[(ua, "Kepler Prime")]))
        s = read_snapshot(p)
        self.assertEqual(len(s.markets), 1)
        self.assertEqual(s.markets[0].item_id, "TRA_ALLOY2")
        self.assertEqual(s.markets[0].address.key, s.address.key)
        self.assertEqual(s.system_names[s.address.key], "Kepler Prime")

    def test_find_newest_skips_meta(self):
        d = self.dir / "st_7656"
        d.mkdir()
        for n in ("save.hg", "save2.hg", "mf_save2.hg"):
            (d / n).write_bytes(b"x")
        os.utime(d / "save.hg", (1, 1))
        self.assertEqual([p.name for p in find_save_files(self.dir)], ["save2.hg", "save.hg"])
        self.assertEqual(newest_save(self.dir).name, "save2.hg")


class TestTrading(TmpDir):
    def setUp(self):
        super().setUp()
        self.store = Store(self.dir)

    def _sys(self, x, econ, wealth="HIGH", name=""):
        s = self.store.touch(Address(0, x, 0, 0, 1), name)
        s.economy, s.wealth = econ, wealth
        return s

    def test_detect_sale_and_learn_need(self):
        here = self._sys(0, "TECH")
        p1, p2 = self.dir / "a.hg", self.dir / "b.hg"
        write_save(p1, make_save(x=0, y=0, z=0, system=1, units=100_000,
                                 ship_slots=[slot("TRA_MINERALS5", 10)]))
        write_save(p2, make_save(x=0, y=0, z=0, system=1, units=100_000 + 10 * 85_000))
        trades = detect_trades(read_snapshot(p1), read_snapshot(p2), self.store)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual((t.kind, t.item_id, t.qty, t.economy), ("sell", "TRA_MINERALS5", 10, "TECH"))
        self.assertAlmostEqual(t.ratio, 1.7)
        self.store.record(t)
        self.assertEqual(self.store.apply_learned(), ["TECH"])
        self.assertEqual(self.store.need_of("TECH"), "Mineral")
        # user choice is never overwritten by learning
        self.store.set_need("TECH", "Energy", "user")
        self.store.apply_learned()
        self.assertEqual(self.store.need_of("TECH"), "Energy")
        self.assertEqual(here.economy, "TECH")

    def test_no_trade_when_moved(self):
        p1, p2 = self.dir / "a.hg", self.dir / "b.hg"
        write_save(p1, make_save(x=0, ship_slots=[slot("TRA_TECH1", 5)]))
        write_save(p2, make_save(x=9, units=2_000_000))
        self.assertEqual(detect_trades(read_snapshot(p1), read_snapshot(p2), self.store), [])

    def test_planner_prefers_demand(self):
        here = self._sys(0, "MINING")
        self._sys(1, "TECH", name="Popyt")
        self._sys(2, "SCIENCE", name="Zwykły")
        self.store.set_need("TECH", "Mineral")
        legs = planner.opportunities(self.store, here, qty=50)
        self.assertEqual([(lot.good.tier, lot.qty) for lot in legs[0].lots], [(5, 30), (4, 20)])
        legs70 = planner.opportunities(self.store, here, qty=70)
        self.assertEqual(legs[0].dest.name, "Popyt")
        self.assertEqual(legs[0].good.id, "TRA_MINERALS5")
        self.assertGreater(legs[0].profit, legs[-1].profit)
        # station stock is limited: tiers 5, 4 then 3 fill a 70-unit hold (30 each by default)
        self.assertEqual([(lot.good.tier, lot.qty) for lot in legs70[0].lots], [(5, 30), (4, 30), (3, 10)])
        self.assertEqual(legs[0].qty, 50)
        route = planner.loop_route(self.store, here, 50, hops=3)
        self.assertEqual(route[0].dest.name, "Popyt")
        self.assertEqual(len({leg.dest.key for leg in route}), len(route))

    def test_hold_advice(self):
        here = self._sys(0, "MINING")
        self._sys(1, "TECH", name="Kupiec")
        self.store.set_need("TECH", "Mineral")
        adv = planner.hold_advice(self.store, here, {"TRA_MINERALS3": 20})
        self.assertEqual(adv[0].verdict, "SELL_THERE")
        self.assertEqual(adv[0].best.name, "Kupiec")
        adv = planner.hold_advice(self.store, self.store.systems[Address(0, 1, 0, 0, 1).key],
                                  {"TRA_MINERALS3": 20})
        self.assertEqual(adv[0].verdict, "SELL_HERE")

    def test_teleport_vs_warp(self):
        here = self._sys(0, "MINING")
        far = self.store.add_manual(Address(0, 40, 0, 0, 3).glyphs(), 0, "Daleko", "TECH", "HIGH")
        near = self._sys(1, "TECH", name="Stacja")
        m_far, j_far, _ = planner.travel_minutes(self.store, here, far)
        m_tp, j_tp, _ = planner.travel_minutes(self.store, here, near)
        self.assertEqual(j_tp, 0)          # both visited -> teleporter
        self.assertGreaterEqual(j_far, 11)  # 16000 ly / 1500 ly
        self.assertLess(m_tp, m_far)

    def test_store_persists(self):
        self._sys(0, "ALLOY", name="Zapisany")
        self.store.set_need("ALLOY", "Exotic")
        self.store.settings.jump_range_ly = 2200
        self.store.save()
        again = Store(self.dir)
        self.assertEqual(again.systems[Address(0, 0, 0, 0, 1).key].name, "Zapisany")
        self.assertEqual(again.need_of("ALLOY"), "Exotic")
        self.assertEqual(again.settings.jump_range_ly, 2200)


if __name__ == "__main__":
    unittest.main()
