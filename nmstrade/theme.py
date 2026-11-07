"""Look and feel inspired by the No Man's Sky interface: near-black glassy
panels, white uppercase headings with wide tracking, thin rules with corner
brackets, inverted (white) selection, coloured currencies.
Only colours and shapes are used; no game artwork.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

BG = "#05070b"          # space black
PANEL = "#0c1118"       # glass panel
PANEL_2 = "#121a24"     # raised rows
LINE = "#273241"        # hairlines
LINE_HI = "#3d4b5e"
TEXT = "#eef2f6"
MUTED = "#8a96a8"
DIM = "#5a6577"
ACCENT = "#ff6b35"      # NMS orange-red
ACCENT_2 = "#ffb347"
UNITS = "#f6c945"       # units yellow
NANITES = "#5fd3f3"     # nanite cyan
QUICKSILVER = "#c89bff"
GOOD = "#7ee08f"
WARN = "#ffcf5a"
BAD = "#ff5a5a"
SELECT_BG = "#f2f4f7"   # NMS inverts the selection to white
SELECT_FG = "#05070b"

WEALTH_COLOR = {"LOW": "#c58a5a", "MED": "#d9dde3", "HIGH": UNITS, "PIRATE": BAD}
CONFLICT_COLOR = {"LOW": GOOD, "MED": WARN, "HIGH": BAD, "PIRATE": BAD}
ECON_COLOR = {
    "TRADE": "#f6c945", "ALLOY": "#c89bff", "SCIENCE": "#5fd3f3", "MINING": "#e0965a",
    "TECH": "#7ea8ff", "MANUFACT": "#b8c2cc", "POWER": "#ff6b35", "PIRATE": BAD,
}


def track(text: str) -> str:
    """Wide letter spacing like NMS headings: 'TRADE' -> 'T R A D E'."""
    words = text.upper().split()
    return "   ".join(" ".join(w) for w in words)


def pick_family(root: tk.Misc, prefs: list[str], fallback: str) -> str:
    have = {f.lower(): f for f in tkfont.families(root)}
    for p in prefs:
        if p.lower() in have:
            return have[p.lower()]
    return fallback


class Fonts:
    def __init__(self, root: tk.Misc, scale: float = 1.0):
        sans = pick_family(root, ["Geomanist", "Rajdhani", "Exo 2", "Exo", "Montserrat",
                                  "Noto Sans", "DejaVu Sans", "Liberation Sans"], "TkDefaultFont")
        mono = pick_family(root, ["JetBrains Mono", "Share Tech Mono", "DejaVu Sans Mono",
                                  "Liberation Mono"], "TkFixedFont")
        s = lambda n: max(7, round(n * scale))
        self.title = tkfont.Font(root, family=sans, size=s(13), weight="bold")
        self.head = tkfont.Font(root, family=sans, size=s(9), weight="bold")
        self.body = tkfont.Font(root, family=sans, size=s(10))
        self.body_b = tkfont.Font(root, family=sans, size=s(10), weight="bold")
        self.small = tkfont.Font(root, family=sans, size=s(8))
        self.big = tkfont.Font(root, family=sans, size=s(18), weight="bold")
        self.num = tkfont.Font(root, family=mono, size=s(12), weight="bold")
        self.glyph = tkfont.Font(root, family=mono, size=s(15), weight="bold")
        self.mono = tkfont.Font(root, family=mono, size=s(9))


def apply_ttk(root: tk.Misc, f: Fonts) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=PANEL, foreground=TEXT, fieldbackground=PANEL_2,
                 bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, troughcolor=BG,
                 font=f.body, focuscolor=ACCENT, insertcolor=TEXT)
    st.configure("TFrame", background=PANEL)
    st.configure("Bg.TFrame", background=BG)
    st.configure("TLabel", background=PANEL, foreground=TEXT)
    st.configure("Muted.TLabel", foreground=MUTED, font=f.small)
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
    st.configure("TNotebook.Tab", background=BG, foreground=MUTED, font=f.head,
                 padding=(16, 7), borderwidth=0)
    st.map("TNotebook.Tab",
           background=[("selected", SELECT_BG), ("active", PANEL_2)],
           foreground=[("selected", SELECT_FG), ("active", TEXT)])
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                 rowheight=round(f.body.metrics("linespace") * 1.75), borderwidth=0, font=f.body)
    st.map("Treeview", background=[("selected", SELECT_BG)], foreground=[("selected", SELECT_FG)])
    st.configure("Treeview.Heading", background=BG, foreground=MUTED, font=f.small,
                 relief="flat", borderwidth=0, padding=(6, 5))
    st.map("Treeview.Heading", background=[("active", PANEL_2)], foreground=[("active", TEXT)])
    st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    st.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT, bordercolor=LINE,
                 lightcolor=LINE, darkcolor=LINE, padding=5)
    st.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    st.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT,
                 arrowcolor=ACCENT, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", PANEL_2)], foreground=[("readonly", TEXT)],
           bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", PANEL_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT_BG)
    root.option_add("*TCombobox*Listbox.selectForeground", SELECT_FG)
    root.option_add("*TCombobox*Listbox.font", f.body)
    st.configure("TCheckbutton", background=PANEL, foreground=TEXT, indicatorcolor=PANEL_2,
                 indicatorbackground=PANEL_2)
    st.map("TCheckbutton", indicatorcolor=[("selected", ACCENT)], background=[("active", PANEL)])
    st.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=PANEL, bordercolor=PANEL,
                 arrowcolor=MUTED, lightcolor=PANEL_2, darkcolor=PANEL_2, gripcount=0)


class Button(tk.Label):
    """Flat NMS-style button: outlined, inverts to white on hover."""

    def __init__(self, master, text: str, command=None, fonts: Fonts | None = None,
                 accent: bool = False, **kw):
        self._accent = accent
        fg = BG if accent else TEXT
        bg = ACCENT if accent else PANEL_2
        super().__init__(master, text=text.upper(), bg=bg, fg=fg, padx=12, pady=5, cursor="hand2",
                         font=fonts.head if fonts else None, highlightthickness=1,
                         highlightbackground=ACCENT if accent else LINE_HI, **kw)
        self._cmd = command
        self.bind("<Enter>", lambda e: self.configure(bg=SELECT_BG, fg=SELECT_FG))
        self.bind("<Leave>", lambda e: self.configure(bg=bg, fg=fg))
        self.bind("<Button-1>", lambda e: self._cmd and self._cmd())


class Panel(tk.Frame):
    """Glass panel with a tracked heading, accent tick and corner brackets."""

    def __init__(self, master, title: str, fonts: Fonts, **kw):
        super().__init__(master, bg=PANEL, highlightthickness=1, highlightbackground=LINE, **kw)
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Frame(head, bg=ACCENT, width=3, height=14).pack(side="left", padx=(0, 8))
        self.title_lbl = tk.Label(head, text=track(title), bg=PANEL, fg=TEXT, font=fonts.head)
        self.title_lbl.pack(side="left")
        self.extra = tk.Frame(head, bg=PANEL)
        self.extra.pack(side="right")
        tk.Frame(self, bg=LINE, height=1).pack(fill="x", padx=12, pady=(2, 6))
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        for relx, rely, anchor in ((0, 0, "nw"), (1, 0, "ne"), (0, 1, "sw"), (1, 1, "se")):
            c = tk.Canvas(self, width=9, height=9, bg=PANEL, highlightthickness=0)
            w, h = 8, 8
            pts = {"nw": (0, h, 0, 0, w, 0), "ne": (0, 0, w, 0, w, h),
                   "sw": (0, 0, 0, h, w, h), "se": (0, h, w, h, w, 0)}[anchor]
            c.create_line(*pts, fill=MUTED, width=2)
            c.place(relx=relx, rely=rely, anchor=anchor)


def glyph_tiles(master, fonts: Fonts) -> tuple[tk.Frame, list[tk.Label]]:
    """12 portal-glyph tiles showing the hex digit of each glyph (0-F)."""
    fr = tk.Frame(master, bg=PANEL)
    tiles = []
    for i in range(12):
        cell = tk.Frame(fr, bg=PANEL)
        cell.pack(side="left", padx=(0, 3) if i != 3 else (0, 10))
        lbl = tk.Label(cell, text="·", width=2, bg=BG, fg=TEXT, font=fonts.glyph,
                       highlightthickness=1, highlightbackground=LINE_HI, pady=2)
        lbl.pack()
        tiles.append(lbl)
    return fr, tiles
