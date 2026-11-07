"""Main window."""
from __future__ import annotations

import queue
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import gamedata as gd
from . import planner
from . import theme as T
from .playerstate import Snapshot
from .session import SessionStats, detect_trades, update_stats
from .store import Store, System
from .watcher import SaveWatcher


def fmt_u(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def econ_text(key: str) -> str:
    if not key:
        return "?"
    return gd.ECONOMY_LABEL.get(key, key)


class Suggest(ttk.Combobox):
    """Combobox that narrows its list as you type (game names)."""

    def __init__(self, master, values: list[str], **kw):
        super().__init__(master, values=values, **kw)
        self._all = values
        self.bind("<KeyRelease>", self._filter)

    def _filter(self, e):
        if e.keysym in ("Return", "Escape", "Up", "Down", "Tab"):
            return
        t = self.get().lower()
        self["values"] = [v for v in self._all if t in v.lower()] or self._all


class App:
    def __init__(self, root: tk.Tk, store: Store, save_file: Path | None = None, demo: bool = False):
        self.root = root
        self.store = store
        self.save_file = save_file
        self.q: queue.Queue = queue.Queue()
        self.snap: Snapshot | None = None
        self.stats = SessionStats()
        self.here: System | None = None
        self._legs: list[planner.Leg] = []
        self.f = T.Fonts(root)
        T.apply_ttk(root, self.f)
        root.title("NMS Trade Computer")
        root.configure(bg=T.BG)
        root.geometry("1320x880")
        root.minsize(980, 640)
        root.attributes("-topmost", bool(store.settings.always_on_top))
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.watcher = None
        if not demo:
            self.start_watcher()
        self.root.after(200, self._pump)

    # ================================================================ layout
    def _build(self) -> None:
        f = self.f
        top = tk.Frame(self.root, bg=T.BG)
        top.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(top, text="◆", bg=T.BG, fg=T.ACCENT, font=f.title).pack(side="left", padx=(0, 10))
        tk.Label(top, text=T.track("Trade Computer"), bg=T.BG, fg=T.TEXT, font=f.title).pack(side="left")
        tk.Label(top, text="  NO MAN'S SKY", bg=T.BG, fg=T.DIM, font=f.head).pack(side="left", padx=8)
        T.Button(top, "Odśwież", self.refresh_now, f).pack(side="right")
        self.status = tk.Label(top, text="Szukam zapisu…", bg=T.BG, fg=T.MUTED, font=f.small)
        self.status.pack(side="right", padx=12)

        upper = tk.Frame(self.root, bg=T.BG)
        upper.pack(fill="x", padx=16)
        upper.columnconfigure(0, weight=3)
        upper.columnconfigure(1, weight=2)
        self._build_system(upper).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_wallet(upper).grid(row=0, column=1, sticky="nsew")

        self.banner = tk.Label(self.root, text="", bg=T.ACCENT, fg=T.BG, font=f.body_b, anchor="w", padx=14, pady=6)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=16, pady=(8, 14))
        self._build_route()
        self._build_hold()
        self._build_systems()
        self._build_demand()
        self._build_log()
        self._build_settings()

    def _kv(self, master, row: int, label: str, col: int = 0) -> tk.Label:
        tk.Label(master, text=label.upper(), bg=T.PANEL, fg=T.MUTED, font=self.f.small).grid(
            row=row, column=col, sticky="w", pady=3, padx=(0, 10))
        v = tk.Label(master, text="—", bg=T.PANEL, fg=T.TEXT, font=self.f.body_b, anchor="w")
        v.grid(row=row, column=col + 1, sticky="w", pady=3)
        return v

    def _build_system(self, master) -> tk.Frame:
        p = T.Panel(master, "Obecny system", self.f)
        b = p.body
        self.sys_name = tk.Label(b, text="—", bg=T.PANEL, fg=T.TEXT, font=self.f.big, anchor="w")
        self.sys_name.grid(row=0, column=0, columnspan=4, sticky="w")
        self.sys_sub = tk.Label(b, text="", bg=T.PANEL, fg=T.MUTED, font=self.f.small, anchor="w")
        self.sys_sub.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
        gfr, self.glyphs = T.glyph_tiles(b, self.f)
        gfr.grid(row=2, column=0, columnspan=3, sticky="w")
        T.Button(b, "Kopiuj", self.copy_glyphs, self.f).grid(row=2, column=3, sticky="e", padx=(8, 0))
        self.booster = tk.Label(b, text="", bg=T.PANEL, fg=T.DIM, font=self.f.mono, anchor="w")
        self.booster.grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 10))

        form = tk.Frame(b, bg=T.PANEL)
        form.grid(row=4, column=0, columnspan=4, sticky="we")
        for i, (lbl, attr, vals) in enumerate((
                ("Nazwa", "e_name", None),
                ("Gospodarka", "e_econ", gd.all_economy_names()),
                ("Zamożność", "e_wealth", gd.all_wealth_names()),
                ("Konflikt", "e_conf", gd.all_conflict_names()))):
            r, c = divmod(i, 2)
            tk.Label(form, text=lbl.upper(), bg=T.PANEL, fg=T.MUTED, font=self.f.small).grid(
                row=r * 2, column=c, sticky="w", padx=(0, 12))
            w = ttk.Entry(form, width=26) if vals is None else Suggest(form, vals, width=24)
            w.grid(row=r * 2 + 1, column=c, sticky="we", padx=(0, 12), pady=(0, 6))
            w.bind("<Return>", lambda e: self.save_here())
            if vals is not None:
                w.bind("<<ComboboxSelected>>", lambda e: self.save_here())
            setattr(self, attr, w)
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        bot = tk.Frame(b, bg=T.PANEL)
        bot.grid(row=5, column=0, columnspan=4, sticky="we")
        self.sys_tags = tk.Frame(bot, bg=T.PANEL)
        self.sys_tags.pack(side="left")
        T.Button(bot, "Zapisz system", self.save_here, self.f, accent=True).pack(side="right")
        tk.Label(b, text="Wpisz dokładnie to, co pokazuje gra (mapa galaktyki / skaner gospodarki), np. "
                         "„Ore Extraction”, „Opulent”.", bg=T.PANEL, fg=T.DIM, font=self.f.small,
                 anchor="w", justify="left").grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))
        return p

    def _build_wallet(self, master) -> tk.Frame:
        p = T.Panel(master, "Zasoby i sesja", self.f)
        b = p.body
        self.w_units = self._money(b, 0, "Jednostki", T.UNITS, "u")
        self.w_nan = self._money(b, 1, "Nanity", T.NANITES, "n")
        self.w_qs = self._money(b, 2, "Rtęć (Quicksilver)", T.QUICKSILVER, "q")
        tk.Frame(b, bg=T.LINE, height=1).grid(row=3, column=0, columnspan=3, sticky="we", pady=8)
        self.w_profit = self._money(b, 4, "Zysk w sesji", T.GOOD, "u")
        self.w_rate = self._money(b, 5, "Tempo", T.TEXT, "u/h")
        self.w_cargo = self._money(b, 6, "Ładownia (towary)", T.TEXT, "szt.")
        self.w_markets = tk.Label(b, text="", bg=T.PANEL, fg=T.DIM, font=self.f.small, anchor="w",
                                  justify="left", wraplength=380)
        self.w_markets.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        b.columnconfigure(1, weight=1)
        return p

    def _money(self, master, row, label, color, unit) -> tk.Label:
        tk.Label(master, text=label.upper(), bg=T.PANEL, fg=T.MUTED, font=self.f.small).grid(
            row=row, column=0, sticky="w", pady=2)
        v = tk.Label(master, text="—", bg=T.PANEL, fg=color, font=self.f.num, anchor="e")
        v.grid(row=row, column=1, sticky="e", pady=2)
        tk.Label(master, text=unit, bg=T.PANEL, fg=T.DIM, font=self.f.small).grid(
            row=row, column=2, sticky="w", padx=(6, 0))
        return v

    def _tree(self, master, cols: list[tuple[str, str, int, str]], height: int = 10) -> ttk.Treeview:
        fr = tk.Frame(master, bg=T.PANEL)
        fr.pack(fill="both", expand=True)
        tv = ttk.Treeview(fr, columns=[c[0] for c in cols], show="headings", height=height)
        for cid, title, width, anchor in cols:
            tv.heading(cid, text=title.upper(), anchor=anchor)
            tv.column(cid, width=width, anchor=anchor, stretch=cid == cols[0][0] or width > 160)
        sb = ttk.Scrollbar(fr, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.tag_configure("odd", background=T.PANEL_2)
        for name, color in (("good", T.GOOD), ("warn", T.WARN), ("bad", T.BAD), ("dim", T.MUTED),
                            ("accent", T.ACCENT_2)):
            tv.tag_configure(name, foreground=color)
        return tv

    def _tab(self, title: str) -> tk.Frame:
        outer = tk.Frame(self.nb, bg=T.BG)
        self.nb.add(outer, text=T.track(title))
        return outer

    def _build_route(self) -> None:
        tab = self._tab("Trasa")
        lp = T.Panel(tab, "Pętla handlowa", self.f)
        lp.pack(side="bottom", fill="x", pady=(8, 0))
        self.loop_box = tk.Frame(lp.body, bg=T.PANEL)
        self.loop_box.pack(fill="x")
        p = T.Panel(tab, "Najlepsze okazje stąd", self.f)
        p.pack(fill="both", expand=True, pady=(8, 0))
        T.Button(p.extra, "Kopiuj glify celu", self.copy_target, self.f).pack(side="right")
        self.route_tv = self._tree(p.body, [
            ("dest", "Cel", 160, "w"), ("econ", "Gospodarka", 150, "w"), ("w", "Zamożn.", 70, "center"),
            ("good", "Kup tutaj", 250, "w"), ("buy", "Kupno ≈", 80, "e"), ("sell", "Sprzedaż ≈", 90, "e"),
            ("profit", "Zysk / kurs", 110, "e"), ("travel", "Podróż", 80, "center"),
            ("rate", "u / h", 100, "e"), ("src", "Źródło", 110, "center")], height=5)
        self.route_tv.bind("<<TreeviewSelect>>", self._route_select)
        self.route_hint = tk.Label(p.body, text="", bg=T.PANEL, fg=T.TEXT, font=self.f.small,
                                   anchor="w", justify="left", wraplength=1200)
        self.route_hint.pack(side="bottom", fill="x", pady=(6, 0))

    def _build_hold(self) -> None:
        tab = self._tab("Ładownia")
        p = T.Panel(tab, "Co zrobić z towarem", self.f)
        p.pack(fill="both", expand=True, pady=(8, 0))
        self.hold_tv = self._tree(p.body, [
            ("good", "Towar", 230, "w"), ("qty", "Ilość", 60, "e"), ("verdict", "Werdykt", 150, "w"),
            ("here", "Tutaj ≈", 100, "e"), ("best", "Najlepiej ≈", 100, "e"), ("where", "Gdzie", 220, "w"),
            ("paid", "Kupione po", 100, "e"), ("note", "Uwagi", 260, "w")])
        tk.Label(p.body, text="Ceny ≈ to szacunek z ceny bazowej towaru, a po Twoich transakcjach – Twoje "
                              "prawdziwe ceny z zapisu gry.", bg=T.PANEL, fg=T.DIM, font=self.f.small,
                 anchor="w").pack(fill="x", pady=(6, 0))

    def _build_systems(self) -> None:
        tab = self._tab("Systemy")
        p = T.Panel(tab, "Twoja baza systemów", self.f)
        p.pack(fill="both", expand=True, pady=(8, 0))
        self.sys_count = tk.Label(p.extra, text="", bg=T.PANEL, fg=T.MUTED, font=self.f.small)
        self.sys_count.pack(side="right")
        self.sys_tv = self._tree(p.body, [
            ("name", "Nazwa", 190, "w"), ("glyphs", "Glify", 140, "w"), ("gal", "Galaktyka", 110, "w"),
            ("econ", "Gospodarka", 150, "w"), ("sells", "Sprzedaje", 110, "w"),
            ("needs", "Potrzebuje", 110, "w"), ("w", "Zamożn.", 70, "center"),
            ("conf", "Konflikt", 80, "center"), ("dist", "Odl. ly", 80, "e"), ("seen", "Ostatnio", 120, "e")],
            height=9)
        self.sys_tv.bind("<<TreeviewSelect>>", self._sys_select)
        form = tk.Frame(p.body, bg=T.PANEL)
        form.pack(fill="x", pady=(10, 0))
        self.m = {}
        for i, (lbl, key, vals, w) in enumerate((
                ("Glify (12 znaków)", "glyphs", None, 16), ("Galaktyka nr", "gal", None, 6),
                ("Nazwa", "name", None, 20), ("Gospodarka", "econ", gd.all_economy_names(), 18),
                ("Zamożność", "wealth", gd.all_wealth_names(), 14), ("Konflikt", "conf", gd.all_conflict_names(), 14),
                ("Notatka", "notes", None, 22))):
            tk.Label(form, text=lbl.upper(), bg=T.PANEL, fg=T.MUTED, font=self.f.small).grid(
                row=0, column=i, sticky="w", padx=(0, 6))
            e = ttk.Entry(form, width=w) if vals is None else Suggest(form, vals, width=w)
            e.grid(row=1, column=i, sticky="we", padx=(0, 6))
            self.m[key] = e
        self.m["gal"].insert(0, "1")
        bt = tk.Frame(p.body, bg=T.PANEL)
        bt.pack(fill="x", pady=(8, 0))
        T.Button(bt, "Dodaj / zapisz", self.manual_save, self.f, accent=True).pack(side="left")
        T.Button(bt, "Usuń zaznaczony", self.manual_delete, self.f).pack(side="left", padx=8)
        self.m_msg = tk.Label(bt, text="Systemy, w których byłeś, dodają się same. Tu możesz dopisać "
                                       "system z glifów portalu (np. z Reddita).",
                              bg=T.PANEL, fg=T.DIM, font=self.f.small)
        self.m_msg.pack(side="left", padx=10)

    def _build_demand(self) -> None:
        tab = self._tab("Popyt")
        p = T.Panel(tab, "Co kupuje każda gospodarka", self.f)
        p.pack(fill="both", expand=True, pady=(8, 0))
        tk.Label(p.body, justify="left", anchor="w", bg=T.PANEL, fg=T.MUTED, font=self.f.body, wraplength=1100,
                 text="Każda gospodarka tanio sprzedaje własne towary, a najwięcej płaci za jedną inną kategorię. "
                      "Wpisz to raz (gra pokazuje to przy towarach na terminalu handlowym) albo po prostu handluj – "
                      "apka wykryje to ze sprzedaży po wysokiej cenie.").pack(fill="x", pady=(0, 6))
        grid = tk.Frame(p.body, bg=T.PANEL)
        grid.pack(fill="x")
        cats = [""] + [f"{gd.CATEGORY_LABEL[c]}  (np. {gd.goods_of(c)[-1].name})" for c in
                       ("Commodity", "Alloy", "Exotic", "Mineral", "Tech", "Component", "Energy")]
        self._cat_by_text = {t: c for t, c in zip(cats[1:], ("Commodity", "Alloy", "Exotic", "Mineral",
                                                               "Tech", "Component", "Energy"))}
        for col, h in enumerate(("Gospodarka", "Nazwy w grze", "Sprzedaje (tanio)", "Potrzebuje (drogo)",
                                 "Skąd wiadomo")):
            tk.Label(grid, text=h.upper(), bg=T.PANEL, fg=T.DIM, font=self.f.small).grid(
                row=0, column=col, sticky="w", padx=(0, 18), pady=(0, 4))
        self.need_boxes: dict[str, ttk.Combobox] = {}
        self.need_src: dict[str, tk.Label] = {}
        for r, e in enumerate(gd.ECONOMIES, start=1):
            tk.Label(grid, text="■ " + gd.ECONOMY_LABEL[e], bg=T.PANEL, fg=T.ECON_COLOR[e],
                     font=self.f.body_b).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 18))
            tk.Label(grid, text=" · ".join(gd.ECONOMY_NAMES[e]), bg=T.PANEL, fg=T.MUTED,
                     font=self.f.small).grid(row=r, column=1, sticky="w", padx=(0, 18))
            sells = gd.SELLS[e]
            tk.Label(grid, text=f"{gd.CATEGORY_LABEL[sells]}", bg=T.PANEL, fg=T.TEXT,
                     font=self.f.body).grid(row=r, column=2, sticky="w", padx=(0, 18))
            cb = ttk.Combobox(grid, values=[c for c in cats if not c.startswith(gd.CATEGORY_LABEL[sells] + " ")],
                              state="readonly", width=30)
            cb.grid(row=r, column=3, sticky="w", padx=(0, 18))
            cb.bind("<<ComboboxSelected>>", lambda ev, e=e: self._need_changed(e))
            self.need_boxes[e] = cb
            src = tk.Label(grid, text="", bg=T.PANEL, fg=T.DIM, font=self.f.small)
            src.grid(row=r, column=4, sticky="w")
            self.need_src[e] = src
        self.learn_lbl = tk.Label(p.body, text="", bg=T.PANEL, fg=T.ACCENT_2, font=self.f.small,
                                  anchor="w", justify="left")
        self.learn_lbl.pack(fill="x", pady=(12, 0))

    def _build_log(self) -> None:
        tab = self._tab("Dziennik")
        p = T.Panel(tab, "Wykryte transakcje", self.f)
        p.pack(fill="both", expand=True, pady=(8, 0))
        self.log_tv = self._tree(p.body, [
            ("time", "Czas", 130, "w"), ("kind", "", 70, "w"), ("good", "Towar", 230, "w"),
            ("qty", "Ilość", 60, "e"), ("price", "Cena / szt.", 110, "e"), ("ratio", "× bazowej", 90, "e"),
            ("total", "Razem", 120, "e"), ("sys", "System", 200, "w"), ("econ", "Gospodarka", 140, "w")])
        tk.Label(p.body, text="Transakcje wykrywane są z różnicy między kolejnymi zapisami gry w tym samym "
                              "systemie (autozapis po wyjściu ze stacji też się liczy).",
                 bg=T.PANEL, fg=T.DIM, font=self.f.small, anchor="w").pack(fill="x", pady=(6, 0))

    def _build_settings(self) -> None:
        tab = self._tab("Ustawienia")
        p = T.Panel(tab, "Ustawienia", self.f)
        p.pack(fill="both", expand=True, pady=(8, 0))
        g = tk.Frame(p.body, bg=T.PANEL)
        g.pack(fill="x", anchor="w")
        st = self.store.settings
        self.s_vars: dict[str, tk.Variable] = {}
        rows = [
            ("cargo_capacity", "Ładowność na kurs (szt., 0 = z zapisu)", int),
            ("stock_per_good", "Zapas jednego towaru na stacji (szt.)", int),
            ("jump_range_ly", "Zasięg skoku hipernapędu (ly)", float),
            ("minutes_per_jump", "Minut na skok", float),
            ("minutes_per_stop", "Minut na lądowanie i handel", float),
            ("minutes_teleport", "Minut na teleport stacyjny", float),
            ("demand_bonus", "Mnożnik ceny przy popycie (szacunek)", float),
            ("local_buy_ratio", "Mnożnik ceny kupna lokalnych towarów", float),
            ("learn_min_ratio", "Próg nauki popytu (× ceny bazowej)", float),
            ("poll_seconds", "Sprawdzaj zapis co (s)", float),
        ]
        for r, (key, label, typ) in enumerate(rows):
            tk.Label(g, text=label.upper(), bg=T.PANEL, fg=T.MUTED, font=self.f.small).grid(
                row=r, column=0, sticky="w", pady=3, padx=(0, 16))
            v = tk.StringVar(value=str(getattr(st, key)))
            ttk.Entry(g, textvariable=v, width=12).grid(row=r, column=1, sticky="w")
            self.s_vars[key] = v
        r = len(rows)
        for key, label in (("use_teleporter", "Między odwiedzonymi stacjami licz teleport"),
                           ("skip_high_conflict", "Pomijaj systemy z wysokim konfliktem"),
                           ("always_on_top", "Okno zawsze na wierzchu")):
            v = tk.BooleanVar(value=bool(getattr(st, key)))
            ttk.Checkbutton(g, text=label, variable=v).grid(row=r, column=0, columnspan=2, sticky="w", pady=3)
            self.s_vars[key] = v
            r += 1
        tk.Label(g, text="FOLDER ZAPISÓW (PUSTE = AUTO)", bg=T.PANEL, fg=T.MUTED, font=self.f.small).grid(
            row=r, column=0, sticky="w", pady=(10, 3))
        self.s_dir = tk.StringVar(value=st.save_dir)
        ttk.Entry(g, textvariable=self.s_dir, width=70).grid(row=r, column=1, sticky="w", pady=(10, 3))
        T.Button(g, "Wybierz…", self._pick_dir, self.f).grid(row=r, column=2, sticky="w", padx=8, pady=(10, 3))
        bt = tk.Frame(p.body, bg=T.PANEL)
        bt.pack(fill="x", pady=(14, 0))
        T.Button(bt, "Zapisz ustawienia", self.save_settings, self.f, accent=True).pack(side="left")
        self.s_msg = tk.Label(bt, text="", bg=T.PANEL, fg=T.GOOD, font=self.f.small)
        self.s_msg.pack(side="left", padx=10)

    # ================================================================ events
    def start_watcher(self) -> None:
        if self.watcher:
            self.watcher.stop()
        root = Path(self.store.settings.save_dir) if self.store.settings.save_dir else None
        self.watcher = SaveWatcher(self.q, root=root, poll=self.store.settings.poll_seconds,
                                   fixed_file=self.save_file)
        self.watcher.start()

    def refresh_now(self) -> None:
        if self.watcher:
            self.watcher.force.set()
        self.render()

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "snapshot":
                    self.on_snapshot(payload)
                elif kind == "status":
                    self.status.configure(text=payload, fg=T.MUTED)
                elif kind == "error":
                    self.status.configure(text="Błąd odczytu: " + payload, fg=T.BAD)
        except queue.Empty:
            pass
        self.root.after(250, self._pump)

    def on_snapshot(self, snap: Snapshot) -> None:
        prev = self.snap
        if snap.address:
            name = snap.system_names.get(snap.address.key, "")
            self.here = self.store.touch(snap.address, name)
        trades = detect_trades(prev, snap, self.store) if prev else []
        for t in trades:
            self.store.record(t)
        update_stats(self.stats, snap, trades)
        if trades:
            self.store.apply_learned()
        self.snap = snap
        self.store.save()
        when = time.strftime("%H:%M:%S", time.localtime(snap.mtime))
        self.status.configure(text=f"{Path(snap.path).name}  ·  {snap.save_name or 'zapis'}  ·  {when}",
                              fg=T.MUTED)
        self.render()

    def save_here(self) -> None:
        if not self.here:
            return
        s = self.here
        s.name = self.e_name.get().strip()
        for widget, attr, fn in ((self.e_econ, "economy", gd.economy_from_name),
                                 (self.e_wealth, "wealth", gd.wealth_from_name),
                                 (self.e_conf, "conflict", gd.conflict_from_name)):
            txt = widget.get().strip()
            setattr(s, attr, fn(txt) or "" if txt else "")
        if s.economy == gd.PIRATE:
            s.wealth = s.wealth or gd.PIRATE
            s.conflict = s.conflict or gd.PIRATE
        self.store.save()
        self.render()

    def manual_save(self) -> None:
        try:
            gal = int(self.m["gal"].get() or "1") - 1
            s = self.store.add_manual(self.m["glyphs"].get(), gal, self.m["name"].get().strip(),
                                      gd.economy_from_name(self.m["econ"].get()) or "",
                                      gd.wealth_from_name(self.m["wealth"].get()) or "",
                                      gd.conflict_from_name(self.m["conf"].get()) or "")
            s.notes = self.m["notes"].get().strip() or s.notes
        except ValueError as e:
            self.m_msg.configure(text=f"Błąd: {e}", fg=T.BAD)
            return
        self.store.save()
        self.m_msg.configure(text=f"Zapisano {s.label()}", fg=T.GOOD)
        self.render()

    def manual_delete(self) -> None:
        for iid in self.sys_tv.selection():
            if self.here and iid == self.here.key:
                continue
            self.store.remove(iid)
        self.store.save()
        self.render()

    def _sys_select(self, _e=None) -> None:
        sel = self.sys_tv.selection()
        if not sel or sel[0] not in self.store.systems:
            return
        s = self.store.systems[sel[0]]
        for key, val in (("glyphs", s.glyphs), ("gal", str(s.galaxy + 1)), ("name", s.name),
                         ("econ", gd.ECONOMY_NAMES.get(s.economy, [""])[0] if s.economy else ""),
                         ("wealth", gd.WEALTH_NAMES.get(s.wealth, [""])[0] if s.wealth in gd.WEALTH_NAMES else
                          ("Black Market" if s.wealth == gd.PIRATE else "")),
                         ("conf", gd.CONFLICT_NAMES.get(s.conflict, [""])[0] if s.conflict else ""),
                         ("notes", s.notes)):
            self.m[key].delete(0, "end")
            self.m[key].insert(0, val)

    def _need_changed(self, econ: str) -> None:
        txt = self.need_boxes[econ].get()
        self.store.set_need(econ, self._cat_by_text.get(txt), "user")
        self.store.save()
        self.render()

    def save_settings(self) -> None:
        st = self.store.settings
        try:
            for key, var in self.s_vars.items():
                cur = getattr(st, key)
                if isinstance(cur, bool):
                    setattr(st, key, bool(var.get()))
                elif isinstance(cur, int):
                    setattr(st, key, int(float(var.get())))
                else:
                    setattr(st, key, float(var.get()))
        except ValueError:
            self.s_msg.configure(text="Popraw liczby", fg=T.BAD)
            return
        changed_dir = st.save_dir != self.s_dir.get().strip()
        st.save_dir = self.s_dir.get().strip()
        self.store.save()
        self.root.attributes("-topmost", bool(st.always_on_top))
        if changed_dir and not self.save_file:
            self.start_watcher()
        self.s_msg.configure(text="Zapisano", fg=T.GOOD)
        self.render()

    def _pick_dir(self) -> None:
        d = filedialog.askdirectory(title="Folder HelloGames/NMS")
        if d:
            self.s_dir.set(d)

    def _clip(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def copy_glyphs(self) -> None:
        if self.snap and self.snap.address:
            self._clip(self.snap.address.glyphs())
            self.status.configure(text="Skopiowano glify obecnego systemu", fg=T.GOOD)

    def copy_target(self) -> None:
        sel = self.route_tv.selection()
        idx = int(sel[0]) if sel else 0
        if self._legs and idx < len(self._legs):
            leg = self._legs[idx]
            self._clip(leg.dest.glyphs)
            self.status.configure(text=f"Skopiowano glify: {leg.dest.label()}", fg=T.GOOD)

    def _route_select(self, _e=None) -> None:
        sel = self.route_tv.selection()
        if sel and self._legs:
            leg = self._legs[int(sel[0])]
            self.route_hint.configure(text=self._leg_hint(leg))

    def _lots_text(self, leg: planner.Leg) -> str:
        extra = "".join(f" +T{lot.good.tier}" for lot in (leg.lots or [])[1:])
        return f"T{leg.good.tier}  {leg.good.name}{extra}"

    def _leg_hint(self, leg: planner.Leg) -> str:
        how = ("teleport ze stacji (byłeś tam)" if leg.jumps == 0 else
               f"{leg.jumps} skok(i) ≈ {fmt_u(leg.distance)} ly · współrzędne {leg.dest.address.signal_booster()}")
        lots = leg.lots or []
        buy = ", ".join(f"{lot.qty} × {lot.good.name} (≈{fmt_u(lot.buy_price)} → ≈{fmt_u(lot.sell_price)} u)"
                        for lot in lots[:3]) + (f" i {len(lots) - 3} tańsze" if len(lots) > 3 else "")
        return (f"► Kup: {buy}.\n   Leć do {leg.dest.label()} [{leg.dest.glyphs}] – {how}. "
                f"Zysk ≈ +{fmt_u(leg.profit)} u.")

    def close(self) -> None:
        if self.watcher:
            self.watcher.stop()
        self.store.save()
        self.root.destroy()

    # ================================================================ render
    def render(self) -> None:
        self._render_system()
        self._render_wallet()
        self._render_route()
        self._render_hold()
        self._render_systems()
        self._render_demand()
        self._render_log()

    def _set_entry(self, w, text: str) -> None:
        if self.root.focus_get() is w:
            return
        w.delete(0, "end")
        w.insert(0, text)

    def _tag(self, master, text, color) -> None:
        tk.Label(master, text=text, bg=T.PANEL, fg=color, font=self.f.small, padx=8, pady=2,
                 highlightthickness=1, highlightbackground=color).pack(side="left", padx=(0, 6))

    def _render_system(self) -> None:
        s, snap = self.here, self.snap
        if not s or not snap or not snap.address:
            return
        a = snap.address
        self.sys_name.configure(text=s.name or "Nienazwany system")
        self.sys_sub.configure(text=f"{gd.galaxy_name(a.galaxy).upper()}  ·  REGION {a.x:+d} {a.y:+d} {a.z:+d}  ·  "
                                    f"SYSTEM 0x{a.system:03X}  ·  PLANETA {a.planet}  ·  WIZYTY {s.visits}")
        for lbl, ch in zip(self.glyphs, a.glyphs()):
            lbl.configure(text=ch)
        self.booster.configure(text=f"WSPÓŁRZĘDNE  {a.signal_booster()}   ·   KOD PORTALU  {a.glyphs()}")
        self._set_entry(self.e_name, s.name)
        self._set_entry(self.e_econ, gd.ECONOMY_NAMES[s.economy][0] if s.economy else "")
        self._set_entry(self.e_wealth, gd.WEALTH_NAMES[s.wealth][0] if s.wealth in gd.WEALTH_NAMES else
                        ("Black Market" if s.wealth == gd.PIRATE else ""))
        self._set_entry(self.e_conf, gd.CONFLICT_NAMES[s.conflict][0] if s.conflict else "")
        for w in self.sys_tags.winfo_children():
            w.destroy()
        if s.economy:
            self._tag(self.sys_tags, econ_text(s.economy).upper(), T.ECON_COLOR.get(s.economy, T.TEXT))
            sells = gd.SELLS.get(s.economy)
            if sells and s.economy != gd.PIRATE:
                self._tag(self.sys_tags, "SPRZEDAJE: " + gd.CATEGORY_LABEL[sells].upper(), T.MUTED)
                need = self.store.need_of(s.economy)
                self._tag(self.sys_tags, "KUPUJE: " + (gd.CATEGORY_LABEL[need].upper() if need else "?"),
                          T.GOOD if need else T.DIM)
        if s.wealth:
            self._tag(self.sys_tags, gd.WEALTH_STARS.get(s.wealth, "") + " " + gd.WEALTH_LABEL[s.wealth].upper(),
                      T.WEALTH_COLOR.get(s.wealth, T.TEXT))
        if s.conflict:
            self._tag(self.sys_tags, "KONFLIKT " + {"LOW": "NISKI", "MED": "ŚREDNI", "HIGH": "WYSOKI",
                                                    "PIRATE": "PIRACI"}[s.conflict],
                      T.CONFLICT_COLOR[s.conflict])
        if not s.economy:
            self.banner.configure(text="◆  NOWY SYSTEM – wpisz gospodarkę i zamożność z mapy galaktyki, "
                                       "żeby dostać porady handlowe.")
            self.banner.pack(fill="x", padx=16, pady=(8, 0), before=self.nb)
        else:
            self.banner.pack_forget()

    def _render_wallet(self) -> None:
        snap = self.snap
        if not snap:
            return
        self.w_units.configure(text=fmt_u(snap.units))
        self.w_nan.configure(text=fmt_u(snap.nanites))
        self.w_qs.configure(text=fmt_u(snap.quicksilver))
        p = self.stats.profit
        self.w_profit.configure(text=("+" if p > 0 else "") + fmt_u(p), fg=T.GOOD if p >= 0 else T.BAD)
        hours = (snap.mtime - (self.stats.start_time or snap.mtime)) / 3600
        self.w_rate.configure(text=fmt_u(p / hours) if hours > 0.05 else "—")
        held = sum(snap.trade_goods().values())
        cap = self._capacity()
        self.w_cargo.configure(text=f"{held} / {cap}")
        if self.here:
            n = sum(1 for m in snap.markets if m.address and m.address.key == self.here.key)
            total = len(snap.markets)
            self.w_markets.configure(text=f"Pamięć rynków w zapisie: {total} wpisów, w tym systemie {n}. "
                                          "Gra pamięta, ile już tu sprzedałeś – ceny wracają z czasem.")

    def _capacity(self) -> int:
        snap = self.snap
        cap = None
        if snap:
            ship = snap.ship_cargo()
            stack = snap.trade_stack_size()
            if ship and stack:
                trade_slots = sum(1 for s in ship.stacks if gd.good(s.item_id))
                cap = (ship.slots_total - ship.slots_used + trade_slots) * stack
        return planner.capacity(self.store, cap)

    def _render_route(self) -> None:
        tv = self.route_tv
        tv.delete(*tv.get_children())
        for w in self.loop_box.winfo_children():
            w.destroy()
        here = self.here
        if not here:
            return
        if not here.economy:
            self.route_hint.configure(text="Najpierw ustaw gospodarkę tego systemu (panel OBECNY SYSTEM).")
            self._legs = []
            return
        qty = self._capacity()
        self._legs = planner.opportunities(self.store, here, qty)
        for i, leg in enumerate(self._legs):
            travel = "teleport" if leg.jumps == 0 else f"{leg.jumps} skok."
            src = leg.sources
            tag = "good" if "popyt" in src or "twoje" in src.split("/")[1] else "dim"
            tv.insert("", "end", iid=str(i), tags=(tag,) + (("odd",) if i % 2 else ()), values=(
                leg.dest.label(), econ_text(leg.dest.economy), gd.WEALTH_STARS.get(leg.dest.wealth, "?"),
                self._lots_text(leg), fmt_u(leg.buy_price), fmt_u(leg.sell_price),
                "+" + fmt_u(leg.profit), travel, fmt_u(leg.per_hour), src))
        if self._legs:
            self.route_hint.configure(text=self._leg_hint(self._legs[0]))
        else:
            known = sum(1 for s in self.store.systems.values() if s.economy and s.key != here.key)
            self.route_hint.configure(text="Brak opłacalnych celów w bazie. " + (
                "Odwiedź więcej systemów i ustaw ich gospodarkę." if known < 2 else
                "Uzupełnij zakładkę POPYT, żeby apka wiedziała, kto płaci najwięcej."))
        route = planner.loop_route(self.store, here, qty)
        if not route:
            tk.Label(self.loop_box, text="—", bg=T.PANEL, fg=T.DIM, font=self.f.body).pack(anchor="w")
            return
        row = tk.Frame(self.loop_box, bg=T.PANEL)
        row.pack(fill="x")
        self._stop(row, here.label(), here.economy, first=True)
        total, minutes = 0.0, 0.0
        for leg in route:
            tk.Label(row, text=f"─ {leg.good.name} ─►", bg=T.PANEL, fg=T.MUTED, font=self.f.small).pack(
                side="left", padx=4)
            self._stop(row, leg.dest.label(), leg.dest.economy)
            total += leg.profit
            minutes += leg.minutes
        rate = total / minutes * 60 if minutes else 0
        tk.Label(self.loop_box, text=f"Razem ≈ +{fmt_u(total)} u w ≈{minutes:.0f} min  ·  ≈{fmt_u(rate)} u/h",
                 bg=T.PANEL, fg=T.UNITS, font=self.f.body_b).pack(anchor="w", pady=(8, 0))

    def _stop(self, master, name: str, econ: str, first: bool = False) -> None:
        color = T.ECON_COLOR.get(econ, T.TEXT)
        fr = tk.Frame(master, bg=T.BG if first else T.PANEL_2, highlightthickness=1, highlightbackground=color)
        fr.pack(side="left")
        tk.Label(fr, text=name[:22], bg=fr["bg"], fg=T.TEXT, font=self.f.body_b, padx=8).pack()
        tk.Label(fr, text=econ_text(econ).upper(), bg=fr["bg"], fg=color, font=self.f.small, padx=8).pack()

    def _render_hold(self) -> None:
        tv = self.hold_tv
        tv.delete(*tv.get_children())
        if not self.snap:
            return
        verdicts = {"SELL_HERE": ("■ SPRZEDAJ TUTAJ", "good"), "SELL_THERE": ("► SPRZEDAJ TAM", "accent"),
                    "HOLD": ("■ TRZYMAJ", "warn")}
        for i, a in enumerate(planner.hold_advice(self.store, self.here, self.snap.trade_goods())):
            text, tag = verdicts[a.verdict]
            tv.insert("", "end", tags=(tag,) + (("odd",) if i % 2 else ()), values=(
                f"T{a.good.tier}  {a.good.name}", a.qty, text, fmt_u(a.here_price) if a.here_price else "—",
                fmt_u(a.best_price) if a.best_price else "—",
                f"{a.best.label()} ({econ_text(a.best.economy)})" if a.best else "—",
                fmt_u(a.paid) if a.paid else "—", a.note))
        if not tv.get_children():
            tv.insert("", "end", tags=("dim",), values=("Brak towarów handlowych na statku i w kombinezonie",
                                                         "", "", "", "", "", "", ""))

    def _render_systems(self) -> None:
        tv = self.sys_tv
        sel = tv.selection()
        tv.delete(*tv.get_children())
        here = self.here
        systems = sorted(self.store.systems.values(), key=lambda s: -s.last_seen)
        for i, s in enumerate(systems):
            dist = gd.distance_ly(here.address, s.address) if here else float("nan")
            need = self.store.need_of(s.economy) if s.economy else None
            tags = ["odd"] if i % 2 else []
            if here and s.key == here.key:
                tags.append("accent")
            elif not s.economy:
                tags.append("dim")
            tv.insert("", "end", iid=s.key, tags=tuple(tags), values=(
                s.label(), s.glyphs, gd.galaxy_name(s.galaxy), econ_text(s.economy),
                gd.CATEGORY_LABEL.get(gd.SELLS.get(s.economy, ""), "—"),
                gd.CATEGORY_LABEL.get(need, "?") if s.economy else "—",
                gd.WEALTH_STARS.get(s.wealth, "?"),
                {"LOW": "niski", "MED": "średni", "HIGH": "wysoki", "PIRATE": "piraci"}.get(s.conflict, "?"),
                "tu" if here and s.key == here.key else
                ("—" if dist != dist or dist == float("inf") else fmt_u(dist)),
                time.strftime("%d.%m %H:%M", time.localtime(s.last_seen)) if s.last_seen else "ręcznie"))
        for iid in sel:
            if tv.exists(iid):
                tv.selection_add(iid)
        known = sum(1 for s in systems if s.economy)
        self.sys_count.configure(text=f"{len(systems)} systemów · {known} z gospodarką")

    def _render_demand(self) -> None:
        learned = self.store.learned_needs()
        for e, cb in self.need_boxes.items():
            cat = self.store.need_of(e)
            cb.set(next((t for t, c in self._cat_by_text.items() if c == cat), ""))
            src = (self.store.needs.get(e) or {}).get("source")
            if src == "user":
                self.need_src[e].configure(text="wpisane", fg=T.MUTED)
            elif src == "learned":
                _c, med, n = learned.get(e, (cat, 0, 0))
                self.need_src[e].configure(text=f"wykryte ({n}× po ×{med:.2f})", fg=T.GOOD)
            else:
                self.need_src[e].configure(text="nieznane", fg=T.DIM)
        missing = [gd.ECONOMY_LABEL[e] for e in gd.ECONOMIES if not self.store.need_of(e)]
        self.learn_lbl.configure(text=("Brakuje: " + ", ".join(missing) + ". Bez tego planer liczy tylko "
                                       "zwykłe ceny (×1.0).") if missing else "Tabela popytu kompletna.")

    def _render_log(self) -> None:
        tv = self.log_tv
        tv.delete(*tv.get_children())
        for i, t in enumerate(reversed(self.store.trades[-500:])):
            g = gd.good(t.item_id)
            s = self.store.systems.get(t.system_key)
            sell = t.kind == "sell"
            tv.insert("", "end", tags=("good" if sell else "warn",) + (("odd",) if i % 2 else ()), values=(
                time.strftime("%d.%m %H:%M", time.localtime(t.ts)), "SPRZEDAŻ" if sell else "KUPNO",
                g.name if g else t.item_id, t.qty, fmt_u(t.unit_price), f"×{t.ratio:.2f}",
                ("+" if sell else "−") + fmt_u(t.unit_price * t.qty), s.label() if s else "?",
                econ_text(t.economy)))
