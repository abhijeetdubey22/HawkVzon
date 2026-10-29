"""Shared colours, fonts, ttk styling and small reusable widgets."""
import tkinter as tk
from tkinter import ttk

# --------------------------------------------------------------------------
# Modern Executive Design System Palette ("Slate & Electric Blue")
# Designed for high legibility, clean visual hierarchy, and modern aesthetics.
# --------------------------------------------------------------------------
C = dict(
    # Backgrounds & Surfaces
    bg="#f8fafc",            # Crisp modern canvas (Slate-50)
    card="#ffffff",          # Pure white card surface
    card_sub="#f1f5f9",      # Subtle card sub-panel / inset (Slate-100)
    header="#0f172a",        # Executive Midnight Slate (Slate-900)
    header_border="#1e293b", # Hairline divider for header (Slate-800)
    statusbar="#ffffff",     # Clean white statusbar
    border="#e2e8f0",        # Clean border (Slate-200)
    border_subtle="#f1f5f9", # Extra soft border (Slate-100)
    video="#090d16",         # Studio obsidian video background
    
    # Typography
    text="#0f172a",          # Deep slate primary text (Slate-900)
    text_sec="#334155",      # Slate-700 secondary text
    muted="#64748b",         # Slate-500 helper / muted text
    subtle="#94a3b8",        # Slate-400 subtle text / placeholders
    
    # Primary Action (Electric Blue / Tech Indigo)
    primary="#2563eb",       # Blue-600
    primary_h="#1d4ed8",     # Blue-700 (hover)
    primary_light="#eff6ff", # Blue-50 (selection / active tint)
    
    # Semantic States (Polished & Vibrant)
    success="#10b981",       # Emerald-500 (Present / Online / Saved)
    success_h="#059669",     # Emerald-600
    success_light="#ecfdf5", # Emerald-50
    
    danger="#ef4444",        # Rose-500 (Absent / Failed / Remove)
    danger_h="#dc2626",      # Rose-600
    danger_light="#fef2f2",  # Rose-50
    
    violet="#6366f1",        # Indigo-500 (AI / Recognition / Accent)
    violet_h="#4f46e5",      # Indigo-600
    violet_light="#eef2ff",  # Indigo-50
    
    amber="#f59e0b",         # Amber-500 (Late / Warning / Connecting)
    amber_h="#d97706",       # Amber-600
    amber_light="#fffbeb",   # Amber-50
    
    grey="#64748b",          # Slate-500
    grey_h="#475569",        # Slate-600
    grey_light="#f1f5f9",    # Slate-100
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
    s.configure("Card.TCheckbutton", background=C["card"], foreground=C["text"], font=FONT)
    s.map("Card.TCheckbutton",
          background=[("active", C["card"])],
          foreground=[("active", C["primary"])])

    # Solid Action Buttons
    buttons = {
        "Primary": (C["primary"], C["primary_h"]),
        "Success": (C["success"], C["success_h"]),
        "Danger": (C["danger"], C["danger_h"]),
        "Violet": (C["violet"], C["violet_h"]),
    }
    for name, (bg, hover) in buttons.items():
        s.configure(f"{name}.TButton", background=bg, foreground="white",
                    borderwidth=0, focusthickness=0, focuscolor=bg,
                    padding=(14, 8), font=FONT_B)
        s.map(f"{name}.TButton",
              background=[("disabled", "#e2e8f0"), ("active", hover)],
              foreground=[("disabled", "#94a3b8")])
              
    # Secondary Outline Button
    s.configure("Secondary.TButton", background="#f1f5f9", foreground=C["text_sec"],
                borderwidth=1, relief="solid", bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"],
                focusthickness=0, padding=(12, 7), font=FONT_B)
    s.map("Secondary.TButton",
          background=[("disabled", "#f8fafc"), ("active", "#e2e8f0")],
          foreground=[("disabled", "#94a3b8"), ("active", C["text"])])

    # Input Controls
    s.configure("TEntry", padding=6, fieldbackground="white", bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"])
    s.configure("TCombobox", padding=6, fieldbackground="white", bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"])
    s.configure("TSpinbox", padding=6, fieldbackground="white", bordercolor=C["border"],
                lightcolor=C["border"], darkcolor=C["border"])
    s.map("TCombobox", fieldbackground=[("readonly", "white")])

    # Tables / Treeview
    s.configure("Treeview", rowheight=30, font=FONT, background="white",
                fieldbackground="white", bordercolor=C["border"], borderwidth=0)
    s.configure("Treeview.Heading", font=FONT_B, background="#f8fafc",
                foreground=C["text_sec"], relief="flat", padding=7,
                bordercolor=C["border"])
    s.map("Treeview.Heading", background=[("active", "#f1f5f9")])
    s.map("Treeview", background=[("selected", C["primary_light"])],
          foreground=[("selected", C["primary"])])

    # Modern Navigation Tabs (Notebook)
    s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(20, 10, 20, 0))
    s.configure("TNotebook.Tab", padding=(22, 9), font=FONT_B, background="#e2e8f0",
                foreground=C["muted"], borderwidth=0)
    s.map("TNotebook.Tab",
          background=[("selected", C["card"]), ("active", "#cbd5e1")],
          foreground=[("selected", C["primary"]), ("active", C["text"])])

    # Custom Scrollbars
    s.configure("Vertical.TScrollbar", background="#e2e8f0", borderwidth=0,
                arrowsize=11, troughcolor=C["bg"])
    s.map("Vertical.TScrollbar", background=[("active", "#cbd5e1")])


def make_card(parent, title, subtitle=None):
    outer = ttk.Frame(parent, style="Card.TFrame", padding=16)
    ttk.Label(outer, text=title, style="CardTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(outer, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(1, 0))
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

    def __init__(self, parent, title, color):
        super().__init__(parent, bg=C["card"], highlightbackground=C["border"],
                         highlightthickness=1, bd=0)
        # 3px top accent bar
        tk.Frame(self, bg=color, height=3).pack(side="top", fill="x")
        
        inner = tk.Frame(self, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=14, pady=10)
        
        header_row = tk.Frame(inner, bg=C["card"])
        header_row.pack(fill="x", anchor="w")
        
        tk.Label(header_row, text="●", font=("Segoe UI", 7), bg=C["card"], fg=color).pack(side="left", padx=(0, 5))
        tk.Label(header_row, text=title.upper(), font=("Segoe UI", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).pack(side="left")
                 
        self.value = tk.Label(inner, text="0", font=FONT_METRIC,
                              bg=C["card"], fg=C["text"])
        self.value.pack(anchor="w", pady=(3, 0))

    def set(self, v):
        self.value.config(text=str(v))


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
