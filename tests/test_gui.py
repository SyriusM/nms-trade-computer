import os
import tempfile
import unittest

try:
    import tkinter as tk
except ImportError:  # pragma: no cover
    tk = None


@unittest.skipIf(tk is None or not os.environ.get("DISPLAY"), "needs Tk and a display (xvfb-run)")
class TestGuiDemo(unittest.TestCase):
    def test_demo_renders_every_tab(self):
        os.environ["NMS_TRADE_CONFIG"] = tempfile.mkdtemp()
        from nmstrade.gui import App
        from nmstrade.main import _demo
        from nmstrade.store import Store

        root = tk.Tk()
        try:
            store = Store()
            app = App(root, store, demo=True)
            snap = _demo(store)
            app.here = store.systems[snap.address.key]
            app.snap = snap
            app.render()
            for i in range(len(app.nb.tabs())):
                app.nb.select(i)
                root.update()
            self.assertGreater(len(app.route_tv.get_children()), 0)
            self.assertEqual(len(app.hold_tv.get_children()), 3)
            self.assertEqual(app.glyphs[0].cget("text"), snap.address.glyphs()[0])
            # typing a game name into the economy box maps it to the economy type
            app.e_econ.delete(0, "end")
            app.e_econ.insert(0, "Ore Extraction")
            app.save_here()
            self.assertEqual(app.here.economy, "MINING")
        finally:
            root.destroy()
