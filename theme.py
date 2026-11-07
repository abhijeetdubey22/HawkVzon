"""Shared colours, fonts, ttk styling and small reusable widgets (Studio Dark Theme)."""
import tkinter as tk
from tkinter import ttk

# --------------------------------------------------------------------------
# Studio Dark Design System ("Cyber Obsidian & Electric Glow")
# Engineered for surveillance command centers, AI vision, and high contrast.
# --------------------------------------------------------------------------
C = dict(
    # Backgrounds & Surfaces
    bg="#0b0f19",            # Deep midnight obsidian canvas
    card="#131b2e",          # Elevated dark slate card surface
    card_sub="#1a243c",      # Inset card section / secondary box
    header="#060911",        # Command bar header (Deepest Charcoal)
    header_border="#1a233a", # Clean hairline divider for header
    statusbar="#060911",     # Clean dark statusbar
    border="#212d47",        # Crisp dark border
    border_subtle="#18233a", # Hairline card border
    video="#03060c",         # Deep cinema black video backdrop
    
    # Typography
    text="#f8fafc",          # High-contrast crisp white primary
    text_sec="#cbd5e1",      # Slate-300 secondary text
    muted="#8899b5",         # Slate-400 helper / muted text
    subtle="#7385a4",        # Slate-400 subtle text / hints (WCAG AA 4.59:1)
    
    # Primary Action (Electric Blue / Cyan)
    primary="#38bdf8",       # Sky-400 / Electric Cyan-Blue
    primary_h="#0284c7",     # Sky-600 (hover)
    primary_btn="#2563eb",   # Solid Blue Button (WCAG AA 5.17:1)
    primary_btn_h="#1d4ed8", # Solid Blue Button Hover
    primary_light="#172554", # Deep blue highlight tint
    
    # Semantic States (Luminous & High-Contrast - WCAG 2.1 AA Compliant)
    success="#047857",       # Emerald-700 (Present / Online / Saved - 5.48:1 contrast with white)
    success_h="#065f46",     # Emerald-800 hover
    success_light="#064e3b", # Emerald-900 tint
    
    danger="#e11d48",        # Rose-600 (Absent / Intruder / Delete - 4.70:1 contrast with white)
    danger_h="#be123c",      # Rose-700 hover
    danger_light="#4c0519",  # Rose-950 tint
    
    violet="#7c3aed",        # Violet-600 (AI / Recognition / WhatsApp - 5.70:1 contrast with white)
    violet_h="#6d28d9",      # Violet-700 hover
    violet_light="#2e1065",  # Violet-950 tint
    
    amber="#fbbf24",         # Amber-400 (Late / Warning / Connecting)
    amber_h="#f59e0b",       # Amber-600
    amber_light="#451a03",   # Amber-950 tint
    
    grey="#1e293b",          # Slate-800 secondary button
    grey_h="#334155",        # Slate-700 hover
    grey_light="#0f172a",    # Slate-900
)

# Typography Scale (Clean Segoe UI hierarchy)
FONT = ("Segoe UI", 10)
FONT_B = ("Segoe UI", 10, "bold")
FONT_H = ("Segoe UI", 11, "bold")
FONT_S = ("Segoe UI", 9)
FONT_T = ("Segoe UI", 13, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_METRIC = ("Segoe UI", 21, "bold")


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

    # Solid Action Buttons (Touch Target: 44px height per Apple HIG / Google Material)
    buttons = {
        "Primary": (C["primary_btn"], C["primary_btn_h"]),
        "Success": (C["success"], C["success_h"]),
        "Danger": (C["danger"], C["danger_h"]),
        "Violet": (C["violet"], C["violet_h"]),
    }
    for name, (bg, hover) in buttons.items():
        s.configure(f"{name}.TButton", background=bg, foreground="white",
                    borderwidth=0, focusthickness=0, focuscolor=bg,
                    padding=(16, 11), font=FONT_B)
        s.map(f"{name}.TButton",
              background=[("disabled", "#1e293b"), ("active", hover)],
              foreground=[("disabled", "#475569")])

    s.configure("Secondary.TButton", background=C["grey"], foreground=C["text"],
                borderwidth=0, focusthickness=0, padding=(16, 11), font=FONT)
    s.map("Secondary.TButton",
          background=[("disabled", "#0f172a"), ("active", C["grey_h"])],
          foreground=[("disabled", "#475569"), ("active", "#ffffff")])

    # Input Fields (Dark Glass Aesthetic)
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

    # Tables / Treeview (High-tech Dark Grid - Touchscreen & Tablet Ready)
    s.configure("Treeview", rowheight=38, font=FONT, background=C["card"],
                fieldbackground=C["card"], foreground=C["text"],
                bordercolor=C["border"], borderwidth=0)
    s.configure("Treeview.Heading", font=FONT_B, background=C["card_sub"],
                foreground=C["text_sec"], relief="flat", padding=10,
                bordercolor=C["border"])
    s.map("Treeview.Heading", background=[("active", C["border"])])
    s.map("Treeview",
          background=[("selected", C["primary_light"])],
          foreground=[("selected", C["primary"])])

    # Modern Navigation Tabs (Notebook - Sleek Dark Pills)
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(20, 10, 20, 0))
    s.configure("TNotebook.Tab", padding=(26, 10), font=FONT_B, background="#111827",
                foreground=C["muted"], borderwidth=0)
    s.map("TNotebook.Tab",
          background=[("selected", C["card"]), ("active", "#1e293b")],
          foreground=[("selected", C["primary"]), ("active", "#ffffff")])

    # Custom Scrollbars
    s.configure("Vertical.TScrollbar", background="#1e293b", borderwidth=0,
                arrowsize=11, troughcolor=C["bg"])
    s.map("Vertical.TScrollbar", background=[("active", "#334155")])


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
    """Executive statistic tile: top accent strip, uppercase caption with dot, high-contrast metric."""

    def __init__(self, parent, title, color, sub=None, font_metric=None):
        super().__init__(parent, bg=C["card"], highlightbackground=C["border"],
                         highlightthickness=1, bd=0)
        # 3px top accent bar
        tk.Frame(self, bg=color, height=3).pack(side="top", fill="x")
        
        inner = tk.Frame(self, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=14, pady=9)
        
        header_row = tk.Frame(inner, bg=C["card"])
        header_row.pack(fill="x", anchor="w")
        
        tk.Label(header_row, text="●", font=("Segoe UI", 7), bg=C["card"], fg=color).pack(side="left", padx=(0, 5))
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
