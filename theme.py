"""Shared colours, fonts, ttk styling and small reusable widgets (Matte Titanium & Stealth Graphite)."""
import tkinter as tk
from tkinter import ttk

# --------------------------------------------------------------------------
# Matte Titanium & Stealth Graphite Design System
# High-precision, zero-fatigue enterprise palette inspired by Apple Pro & Linear.
# Strict 60-30-10 rule: 90% neutral architectural matte, 10% disciplined telemetry.
# --------------------------------------------------------------------------
C = dict(
    # Backgrounds & Surfaces (Neutral Matte Titanium & Stealth Graphite)
    bg="#09090b",            # True neutral deep matte charcoal (Zinc 950)
    card="#121215",          # Elevated matte graphite card surface
    card_sub="#18181d",      # Inset card section / secondary box
    header="#09090b",        # Command bar header (Seamless Matte)
    header_border="#1f1f24", # Ultra-fine 1px hairline divider
    statusbar="#09090b",     # Minimal statusbar
    border="#222228",        # Subtle high-precision card border
    border_subtle="#1a1a20", # Hairline card border
    video="#000000",         # Cinema true black video backdrop
    
    # Typography (Zinc High-Contrast Scale - Zero Eye Strain, WCAG AAA)
    text="#f4f4f5",          # Zinc 100 crisp off-white primary (16.5:1 contrast)
    text_sec="#a1a1aa",      # Zinc 400 neutral secondary
    muted="#71717a",         # Zinc 500 helper / muted text
    subtle="#52525b",        # Zinc 600 subtle metadata & hints
    
    # Primary Action (Authoritative Enterprise Blue)
    primary="#3b82f6",       # Blue 500
    primary_h="#2563eb",     # Blue 600 (hover)
    primary_btn="#2563eb",   # Solid Enterprise Blue
    primary_btn_h="#1d4ed8", # Deep Blue hover
    primary_light="#172554", # Deep blue highlight tint
    
    # Semantic Status Telemetry (Subtle, Disciplined, Never Loud Neon)
    success="#10b981",       # Emerald 500 (Verified present / live)
    success_h="#059669",
    success_light="#13241b",
    
    danger="#ef4444",        # Red 500 (Subdued crimson alert / intruder)
    danger_h="#dc2626",
    danger_light="#291316",
    
    violet="#6366f1",        # Indigo 500 (Calm telemetry / facial AU)
    violet_h="#4f46e5",
    violet_light="#1c1936",
    
    amber="#f59e0b",         # Amber 500 (Warning / Pending / Overstay)
    amber_h="#d97706",
    amber_light="#251c11",
    
    grey="#1c1c21",          # Matte graphite secondary button
    grey_h="#282830",        # Matte hover
    grey_light="#121216",
)

# Typography Scale (Clean Segoe UI hierarchy)
FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_H = ("Segoe UI", 11, "bold")
FONT_S = ("Segoe UI", 9)
FONT_T = ("Segoe UI", 13, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_METRIC = ("Segoe UI", 20, "bold")


def apply_style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    
    # Global defaults
    s.configure(".", font=FONT, background=C["bg"], foreground=C["text"])
    s.configure("TFrame", background=C["bg"])
    
    # Cards & Containers
    s.configure("Card.TFrame", background=C["card"], borderwidth=1,
                relief="solid", bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"])
    s.configure("Inner.TFrame", background=C["card"])
    s.configure("Card.TLabel", background=C["card"], foreground=C["text"], font=FONT)
    s.configure("CardTitle.TLabel", background=C["card"], foreground=C["text"], font=FONT_H)
    s.configure("Muted.TLabel", background=C["card"], foreground=C["muted"], font=FONT_S)
    
    # Checkbuttons
    s.configure("Card.TCheckbutton", background=C["card"], foreground=C["text"], font=FONT,
                indicatorbackground=C["card_sub"], indicatorforeground=C["primary"])
    s.map("Card.TCheckbutton",
          background=[("active", C["card"])],
          foreground=[("active", C["primary"])],
          indicatorbackground=[("active", C["border"])])

    # Refined Enterprise Buttons (Zero rainbow clashing - Apple Pro / Linear grade)
    # Primary Action (Solid Enterprise Blue)
    s.configure("Primary.TButton", background=C["primary_btn"], foreground="#ffffff",
                borderwidth=0, focusthickness=0, focuscolor=C["primary_btn"],
                padding=(16, 10), font=FONT_B)
    s.map("Primary.TButton",
          background=[("disabled", "#18181c"), ("active", C["primary_btn_h"])],
          foreground=[("disabled", "#52525b")])

    # Secondary Action (Matte Graphite)
    s.configure("Secondary.TButton", background=C["grey"], foreground=C["text"],
                borderwidth=1, bordercolor=C["border"], focusthickness=0, padding=(16, 10), font=FONT)
    s.map("Secondary.TButton",
          background=[("disabled", "#121215"), ("active", C["grey_h"])],
          foreground=[("disabled", "#52525b"), ("active", "#ffffff")])

    # Subtle State Buttons (Restrained, elegant, not screaming)
    s.configure("Success.TButton", background=C["primary_btn"], foreground="#ffffff",
                borderwidth=0, focusthickness=0, padding=(16, 10), font=FONT_B)
    s.map("Success.TButton",
          background=[("disabled", "#18181c"), ("active", C["primary_btn_h"])],
          foreground=[("disabled", "#52525b")])

    s.configure("Danger.TButton", background=C["grey"], foreground="#f87171",
                borderwidth=1, bordercolor="#3b1d22", focusthickness=0, padding=(16, 10), font=FONT)
    s.map("Danger.TButton",
          background=[("disabled", "#121215"), ("active", "#2a1518")],
          foreground=[("disabled", "#52525b"), ("active", "#fca5a5")])

    s.configure("Violet.TButton", background=C["grey"], foreground="#c084fc",
                borderwidth=1, bordercolor="#2e243d", focusthickness=0, padding=(16, 10), font=FONT)
    s.map("Violet.TButton",
          background=[("disabled", "#121215"), ("active", "#251c33")],
          foreground=[("disabled", "#52525b"), ("active", "#e9d5ff")])

    # Input Fields (Matte Glass Aesthetic)
    s.configure("TEntry", padding=8, fieldbackground=C["card_sub"],
                foreground=C["text"], bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"],
                insertcolor=C["text"])
    s.configure("TCombobox", padding=8, fieldbackground=C["card_sub"],
                foreground=C["text"], bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"],
                arrowcolor=C["text"])
    s.configure("TSpinbox", padding=8, fieldbackground=C["card_sub"],
                foreground=C["text"], bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"],
                arrowcolor=C["text"])
    s.map("TCombobox",
          fieldbackground=[("readonly", C["card_sub"])],
          foreground=[("readonly", C["text"])],
          selectbackground=[("readonly", C["primary_light"])],
          selectforeground=[("readonly", C["text"])])

    # Tables / Treeview (High-Precision Dark Grid)
    s.configure("Treeview", rowheight=36, font=FONT, background=C["card"],
                fieldbackground=C["card"], foreground=C["text"],
                bordercolor=C["border"], borderwidth=0)
    s.configure("Treeview.Heading", font=FONT_B, background=C["card_sub"],
                foreground=C["text_sec"], relief="flat", padding=10,
                bordercolor=C["border"])
    s.map("Treeview.Heading", background=[("active", C["border"])])
    s.map("Treeview",
          background=[("selected", C["primary_light"])],
          foreground=[("selected", "#ffffff")])

    # Modern Navigation Tabs (Notebook - Sleek Architectural Tabs)
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(20, 10, 20, 0))
    s.configure("TNotebook.Tab", padding=(24, 9), font=FONT_B, background="#141418",
                foreground=C["muted"], borderwidth=0)
    s.map("TNotebook.Tab",
          background=[("selected", C["card"]), ("active", "#1c1c22")],
          foreground=[("selected", C["text"]), ("active", "#ffffff")])

    # Custom Scrollbars
    s.configure("Vertical.TScrollbar", background="#1c1c22", borderwidth=0,
                arrowsize=11, troughcolor=C["bg"])
    s.map("Vertical.TScrollbar", background=[("active", "#2c2c36")])


def make_card(parent, title, subtitle=None):
    outer = ttk.Frame(parent, style="Card.TFrame", padding=16)
    ttk.Label(outer, text=title, style="CardTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(outer, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
    body = ttk.Frame(outer, style="Inner.TFrame")
    body.pack(fill="both", expand=True, pady=(10, 0))
    return outer, body


def tag_colors(tree):
    for tag, color in (("present", C["success"]), ("late", C["amber"]),
                       ("absent", C["danger"]), ("idle", C["muted"]),
                       ("ok", C["success"]), ("warn", C["amber"]),
                       ("bad", C["danger"]), ("rec", C["violet"])):
        tree.tag_configure(tag, foreground=color)


def make_tree(parent, columns, heads, widths, height=6, anchors=None):
    """Treeview + vertical scrollbar, packed into `parent`. Returns the tree."""
    wrap = ttk.Frame(parent, style="Inner.TFrame")
    wrap.pack(fill="both", expand=True)
    tree = ttk.Treeview(wrap, columns=columns, show="headings", height=height,
                        selectmode="browse")
    for i, col in enumerate(columns):
        tree.heading(col, text=heads[i])
        tree.column(col, width=widths[i], minwidth=40,
                    anchor=(anchors[i] if anchors else "center"))
    sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tag_colors(tree)
    return tree


def fill_tree(tree, rows, sigs, key):
    """rows = [(iid, values, tags)]. Rebuilds only when something changed and
    keeps selection + scroll position. Returns True if it rebuilt."""
    sig = tuple((iid, tuple(vals), tuple(tags)) for iid, vals, tags in rows)
    if sigs.get(key) == sig:
        return False
    sigs[key] = sig
    sel = list(tree.selection())
    y = tree.yview()[0]
    tree.delete(*tree.get_children())
    for iid, vals, tags in rows:
        tree.insert("", "end", iid=iid, values=vals, tags=tags)
    keep = [i for i in sel if tree.exists(i)]
    if keep:
        tree.selection_set(keep)
    tree.yview_moveto(y)
    return True


class Kpi(tk.Frame):
    """Executive statistic tile: matte graphite card, subtle hairline accent, high-precision metric."""

    def __init__(self, parent, title, color, sub=None, font_metric=None):
        super().__init__(parent, bg=C["card"], highlightbackground=C["border"],
                         highlightthickness=1, bd=0)
        # 2px subtle architectural accent bar (calm, disciplined)
        tk.Frame(self, bg=color, height=2).pack(side="top", fill="x")
        
        inner = tk.Frame(self, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=14, pady=9)
        
        header_row = tk.Frame(inner, bg=C["card"])
        header_row.pack(fill="x", anchor="w")
        
        # Subtle 6px status dot
        tk.Label(header_row, text="●", font=("Segoe UI", 6), bg=C["card"], fg=color).pack(side="left", padx=(0, 6))
        tk.Label(header_row, text=title.upper(), font=("Segoe UI", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).pack(side="left")
                 
        f_val = font_metric if font_metric else ("Segoe UI", 16, "bold")
        self.value = tk.Label(inner, text="0", font=f_val,
                              bg=C["card"], fg=C["text"])
        self.value.pack(anchor="w", pady=(2, 0))

        self.sub_label = tk.Label(inner, text=sub or "", font=("Segoe UI", 8),
                                  bg=C["card"], fg=C["subtle"])
        self.sub_label.pack(anchor="w", pady=(1, 0))

    def set(self, v, sub=None):
        self.value.config(text=str(v))
        if sub is not None:
            self.sub_label.config(text=str(sub))


class ScrollFrame(tk.Frame):
    """Vertically scrollable container. Put widgets into `.inner`."""

    def __init__(self, parent, width=380, bg=None):
        bg = bg or C["bg"]
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=width)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self._vsb_visible = False
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", self._wheel, add="+")
        self.bind_all("<Button-5>", self._wheel, add="+")

    def _on_scroll(self, first, last):
        self.vsb.set(first, last)
        need = not (float(first) <= 0.0 and float(last) >= 1.0)
        if need and not self._vsb_visible:
            self.vsb.pack(side="right", fill="y")
            self._vsb_visible = True
        elif not need and self._vsb_visible:
            self.vsb.pack_forget()
            self._vsb_visible = False

    def _wheel(self, event):
        try:
            w = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while w is not None:
            if w is self:
                break
            w = w.master
        else:
            return
        if not self._vsb_visible:
            return
        if getattr(event, "num", 0) == 4:
            step = -1
        elif getattr(event, "num", 0) == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step * 2, "units")
