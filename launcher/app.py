# -*- coding: utf-8 -*-
"""
DeepSeek Harness Offline — Desktop Launcher
============================================
HYBRID DESIGN (user request):
  * UI LAYOUT rolled back to the ORIGINAL simple CustomTkinter baseline —
    no self-drawn Canvas gradients, no GradientButton, no GlassCard, no
    brand signature line, no hand-drawn logo.
  * BUT: COLOR PALETTE stays 100% DeepSeek Official (chat.deepseek.com) dark
    as applied in the previous modern skin: obsidian near-black canvas,
    indigo→lilac brand accent (#4D6BFE→#7A79FF) for primary CTA,
    charcoal surfaces with 1px BORDER hairline, 3-level grayscale text.

All non-UI bug fixes are preserved:
  - util bar pinned to root (NOT inside body) so it never gets clipped by
    expanding log area (uses place + reflow_util with exact pixel widths).
  - status_detail wraplength auto-synced to status card body width
    (token?=... URLs wrap correctly instead of getting clipped).
  - Window X-button: call_once + after(320 ms) FAILSAFE hard destroy so users
    can ALWAYS close (even if Tk animation loop stalls).
  - engine.py lifecycle & token capture untouched.
  - CTk appearance_mode("dark") + our tokens override CTk defaults via
    explicit fg_color / text_color / hover_color on every widget.
"""

from __future__ import annotations

import os
import queue
import sys
import time
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple

import customtkinter as ctk
import tkinter as tk

# Ensure launcher dir is on sys.path so `from engine import ...` works when
# pythonw.exe is launched with an absolute script path and arbitrary cwd.
_LAUNCHER_DIR = Path(__file__).resolve().parent
if str(_LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(_LAUNCHER_DIR))

from engine import (  # noqa: E402
    DSHEngine,
    EngineState,
    open_logs_folder,
    open_workspace_folder,
)


# =============================================================================
#  THEME: single source of truth
#  DeepSeek Official (chat.deepseek.com) Dark semantic tokens
# =============================================================================

ctk.set_appearance_mode("dark")
try:
    ctk.set_default_color_theme("dark-blue")
except Exception:
    pass

BG_BASE       = "#131316"   # obsidian canvas base
BG_DEEP       = "#15151A"   # vertical vignette bottom
SURFACE       = "#1C1C21"   # card surface (elevation 1)
RAISED        = "#26262D"   # pill / hover chip / input bg
BORDER        = "#2F2F38"   # 1 px hairline between surfaces
BORDER_HOVER  = "#3A3A46"
TEXT_PRIMARY  = "#FFFFFF"
TEXT_SECOND   = "#B3B8C6"
TEXT_MUTED    = "#6B7084"

# Brand (indigo → lilac)
ACCENT_START  = "#4D6BFE"
ACCENT_MID    = "#6679FF"
ACCENT_END    = "#7A79FF"
# Single "accent solid" used for CTk flat buttons (CTk only takes one colour).
# We hover to a lighter tint (mix white 15%) to feel like the gradient.
ACCENT        = ACCENT_START   # solid fill used by CTkButton primary
ACCENT_HOVER  = ACCENT_MID     # hover variant (slightly lighter)
ACCENT_TEXT   = "#FFFFFF"

DANGER        = "#B4233A"
DANGER_HOVER  = "#C42746"
DANGER_TEXT   = "#FFFFFF"

OPEN          = OPEN_BG = OPEN_HOVER = OPEN_TEXT = "#000000"  # placeholder, re-assigned below
# Use indigo→lilac as open/web-ui secondary
OPEN          = OPEN_BG = "#5B52E8"
OPEN_HOVER    = "#7069F5"
OPEN_TEXT     = "#FFFFFF"

UTIL_BG       = UTIL_START = "#23232B"
UTIL_HOVER    = "#30303B"
UTIL_TEXT     = TEXT_PRIMARY

CLEAR_BG      = "#202027"
CLEAR_HOVER   = "#2E2E38"
CLEAR_TEXT    = TEXT_SECOND

# Status chips: (label text, dot color, chip bg solid, text color)
STATUS_CHIP = {
    # (text, dot, chip_bg, text, card_surface_bg)
    EngineState.STOPPED:  ("未启动",    TEXT_MUTED,   RAISED,    TEXT_SECOND, SURFACE),
    EngineState.STARTING: ("启动中…",   "#4299E1",    "#1A2332", "#A9CDE8",   SURFACE),
    EngineState.RUNNING:  ("运行中",     "#10B981",    "#15231F", "#9FE6C8",   SURFACE),
    EngineState.ERROR:    ("出错",       "#F43F5E",    "#2A161B", "#F5BDC7",   SURFACE),
}


# =============================================================================
#  Helpers: colour interpolation + easing
# =============================================================================

def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return 200, 200, 200
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb) -> str:
    r, g, b = [max(0, min(255, int(round(c)))) for c in rgb]
    return "#%02x%02x%02x" % (r, g, b)


def _mix(a: str, b: str, t: float) -> str:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    return _rgb_to_hex((ra + (rb - ra) * t,
                        ga + (gb - ga) * t,
                        ba + (bb - ba) * t))


def _ease_out_cubic(t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 1 - (1 - t) ** 3


def _ease_in_out_cubic(t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


# =============================================================================
#  Mini animation runtime — used ONLY for entrance/close fades now.
#  Kept intentionally tiny: no button hover tweens, no spinner/pulse loops
#  (those use CTk's built-in hover behaviour now to avoid draw bugs).
# =============================================================================

class Tweener:
    __slots__ = ("_tweens", "_next_id")

    def __init__(self) -> None:
        self._tweens: dict = {}
        self._next_id = 1

    def tween(self, duration_ms: int,
              on_update: Callable[[float], None],
              on_done: Optional[Callable[[], None]] = None,
              delay_ms: int = 0,
              easing: Callable[[float], float] = _ease_out_cubic) -> int:
        tid = self._next_id
        self._next_id += 1
        start = time.perf_counter() + delay_ms / 1000.0

        def _upd(t_raw: float) -> None:
            t = easing(t_raw) if easing else t_raw
            on_update(t)

        self._tweens[tid] = (start, duration_ms, _upd, on_done)
        return tid

    def tick(self) -> None:
        now = time.perf_counter()
        done = []
        for tid, (start, dur, on_upd, on_done) in list(self._tweens.items()):
            if now < start:
                continue
            elapsed_ms = (now - start) * 1000.0
            t = 1.0 if dur <= 0 else min(1.0, elapsed_ms / dur)
            try:
                on_upd(t)
            except Exception:
                done.append(tid)
                continue
            if t >= 1.0:
                if on_done is not None:
                    try:
                        on_done()
                    except Exception:
                        pass
                done.append(tid)
        for tid in done:
            self._tweens.pop(tid, None)


# =============================================================================
#  Main window
# =============================================================================

class LauncherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("DSH 启动器")
        self.geometry("980x720")
        self.minsize(760, 640)
        self.configure(fg_color=BG_BASE)

        # Startup entrance fade-in (alpha 0 -> 1 over ~300ms)
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        self._tw = Tweener()

        # Engine + thread bridge ------------------------------------------
        # NOTE: DSHEngine constructor takes ONLY the three callbacks —
        #   on_log / on_ready / on_state_change
        # No 'root_dir', no 'log_to_file', no 'on_state' alias.
        # Log file setup is handled INSIDE engine (uses _app_root via env).
        self.engine = DSHEngine(on_ready=self._on_engine_ready,
                                on_state_change=self._on_engine_state,
                                on_log=self._on_engine_log)
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._state = EngineState.STOPPED
        self._last_fade_tag = (None, None)  # status detail fade

        # Visual structure -------------------------------------------------
        # Use the same 3-layer layout proven to keep the util bar visible:
        #   bg_layer (tk.Canvas that fills the whole window)
        #   _surface : place(relx=0 rely=0 relwidth=1 relheight=1) — parent of all interactive widgets
        #     _title  : top brand header
        #     _body   : cards / buttons (pad-bottom reserved for util row)
        #     _util   : place pinned to surface BOTTOM, NEVER inside _body
        #
        # Title height bumped to 92 px because "DSH 启动器" at 20pt bold
        # Chinese glyphs need a bit more vertical breathing room on Windows
        # Tk 8.6 (previously 76 px caused the bottom stroke of 启动/器 to
        # render partially clipped on some DPI / font hinting modes).
        self._title_h = 92
        self._pad = 22
        self._util_row_height = 64

        # Background: plain solid BG_BASE — no gradients, no effects (user said
        # "revert layout to first version").
        self._bg_layer = tk.Canvas(self, highlightthickness=0, bd=0, bg=BG_BASE)
        self._bg_layer.pack(fill="both", expand=True)

        self._surface = tk.Frame(self, bg=BG_BASE, highlightthickness=0)
        self._surface.place(in_=self._bg_layer, relx=0, rely=0,
                            relwidth=1.0, relheight=1.0)

        self._build_title()

        self._body = tk.Frame(self._surface, bg=BG_BASE, highlightthickness=0)
        self._body.pack(side="top", fill="both", expand=False,
                        padx=self._pad, pady=(self._title_h, 0))
        # Reserve bottom padding so tall log cards don't overlap util row.
        self._body.pack_configure(pady=(self._title_h, self._util_row_height + 18))

        self._build_ui()
        self._build_util_bar()

        # Status detail wrapper sync
        self.status_card_body.bind("<Configure>",
                                   lambda _e: self._resize_status_wrap(), add="+")
        self.status_detail.bind("<Configure>",
                                lambda _e: self._resize_status_wrap(), add="+")

        # Util bar width always = surface width - 2*pad (handles Windows Tk
        # clamping negative place() widths to 0).
        self._surface.bind("<Configure>", self._reflow_util, add="+")

        # X button close (double-failsafe).
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Kick off the 30 FPS ticker (tween fades + log drain)
        self.after(25, self._tick)

        # Apply initial STOPPED state
        self._apply_state(EngineState.STOPPED)

        # Entrance fade-in: 0 → 1 alpha over ~320 ms.
        self._do_entrance_fade()

    # ------------------------------------------------------------------
    # Title bar (LEGACY simple: single label + sublabel on surface panel)
    # ------------------------------------------------------------------
    def _build_title(self) -> None:
        bar = tk.Frame(self._surface, bg=BG_BASE, highlightthickness=0)
        bar.place(x=0, y=0, relwidth=1.0, height=self._title_h)
        # No signature line per user request ("蓝色的分割线还是签名线不需要").
        # Title bar is kept clean — just two rows of text on obsidian BG.

        self._title_label = tk.Label(
            bar,
            text="DSH 启动器",
            fg=TEXT_PRIMARY,
            bg=BG_BASE,
            anchor="w",
            # 19pt bold keeps the text tall but leaves ~10 px of top+bottom
            # padding inside a 36 px bounding box — avoids clipping the
            # bottom strokes of Chinese 启 / 动 / 器 on Windows.
            font=("Microsoft YaHei UI", 19, "bold"),
            pady=4,      # headroom inside the Label widget to prevent clipping
            padx=0,
        )
        # y=18 was too tight for 20pt Chinese: the 14-px baseline-to-bottom
        # descent extends past the 76px bar; y=20 on a 92px bar gives
        # approx 20(top) + 34(font ascender) + 8(internal pad) = 62, leaving
        # room for 器 丿 bottom before the sub-label starts.
        self._title_label.place(x=self._pad, y=20, anchor="nw")
        self._sub_label = tk.Label(
            bar,
            text="DeepSeek Harness 启动器",
            fg=TEXT_SECOND,
            bg=BG_BASE,
            anchor="w",
            font=("Microsoft YaHei UI", 11),
            pady=2,
        )
        # y=58: sits 4 px below a 34px-tall title label (placed at y=20),
        # and sits about 24 px above the bottom of a 92px tall title bar
        # — no clipping possible on any stroke.
        self._sub_label.place(x=self._pad, y=58, anchor="nw")

    # ------------------------------------------------------------------
    # Body: status card → buttons → log card (LEGACY order)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # ---- Status card (single CTkFrame with 1px BORDER — NO extra
        #      outer frame so we avoid "two nested border" visual glitches
        #      and the faint light-grey outline the user reported.) -------
        self.status_card_body = ctk.CTkFrame(
            self._body,
            corner_radius=16,
            border_width=1,
            border_color=BORDER,
            fg_color=SURFACE,
            bg_color=BG_BASE,
        )
        self.status_card_body.pack(fill="x", pady=(0, 18))

        chip_row = tk.Frame(self.status_card_body, bg=SURFACE,
                            highlightthickness=0)
        chip_row.pack(fill="x", padx=18, pady=(18, 10))
        # Status chip: coloured dot + text on RAISED pill
        self._chip_holder = tk.Frame(chip_row, bg=SURFACE,
                                     highlightthickness=0)
        self._chip_holder.pack(side="left")
        self._chip_bg: Optional[ctk.CTkFrame] = None
        self._chip_dot: Optional[tk.Label] = None
        self._chip_text: Optional[tk.Label] = None
        self._ensure_chip(EngineState.STOPPED)

        self.status_label = tk.Label(
            chip_row,
            text="引擎已停止，点击下方按钮重新启动。",
            fg=TEXT_SECOND,
            bg=SURFACE,
            anchor="e",
            font=("Microsoft YaHei UI", 10),
        )
        self.status_label.pack(side="right")

        # Status detail: auto-wrap URL line
        self.status_detail = tk.Label(
            self.status_card_body,
            text="\n",
            fg=TEXT_MUTED,
            bg=SURFACE,
            anchor="w",
            justify="left",
            font=("Microsoft YaHei UI", 10),
        )
        self.status_detail.pack(fill="x", padx=18, pady=(0, 18))

        # ---- Primary + secondary action buttons --------------------------
        # Main button (primary — brand indigo→lilac solid)
        self.btn_start = ctk.CTkButton(
            self._body,
            text="▶  启动 DeepSeek Harness",
            command=self._on_click_start,
            height=50,
            corner_radius=14,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=ACCENT_TEXT,
            border_width=1,
            border_color=_mix(ACCENT, ACCENT_END, 0.5),
            font=("Microsoft YaHei UI", 13, "bold"),
            cursor="hand2",
            anchor="center",
        )
        self.btn_start.pack(fill="x", pady=(0, 14))

        sec_row = tk.Frame(self._body, bg=BG_BASE, highlightthickness=0)
        sec_row.pack(fill="x", pady=(0, 18))

        self.btn_stop = ctk.CTkButton(
            sec_row,
            text="■  停止引擎",
            command=self._on_click_stop,
            state=tk.DISABLED,
            height=40,
            corner_radius=12,
            fg_color=DANGER,
            hover_color=DANGER_HOVER,
            text_color=DANGER_TEXT,
            border_width=1,
            border_color=_mix(DANGER, "#000000", 0.25),
            font=("Microsoft YaHei UI", 12, "bold"),
            cursor="hand2",
            anchor="center",
        )
        self.btn_stop.pack(side="left", expand=True, fill="x", padx=(0, 8))

        self.btn_open = ctk.CTkButton(
            sec_row,
            text="⬀  打开 Web UI",
            command=self._on_click_open_browser,
            state=tk.DISABLED,
            height=40,
            corner_radius=12,
            fg_color=OPEN_BG,
            hover_color=OPEN_HOVER,
            text_color=OPEN_TEXT,
            border_width=1,
            border_color=_mix(OPEN_BG, "#000000", 0.25),
            font=("Microsoft YaHei UI", 12, "bold"),
            cursor="hand2",
            anchor="center",
        )
        self.btn_open.pack(side="left", expand=True, fill="x", padx=(8, 0))

        # ---- Log card (single CTkFrame — NO extra outer frame to avoid the
        #      faint double-border / light-outlining effect the user saw.)
        log_inner = ctk.CTkFrame(
            self._body,
            corner_radius=16,
            border_width=1,
            border_color=BORDER,
            fg_color=SURFACE,
            bg_color=BG_BASE,
        )
        log_inner.pack(fill="both", expand=True)

        log_head = tk.Frame(log_inner, bg=SURFACE, highlightthickness=0)
        log_head.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(log_head, text="运行日志",
                 fg=TEXT_PRIMARY, bg=SURFACE, anchor="w",
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        self.btn_clear_log = ctk.CTkButton(
            log_head,
            text="清空",
            command=self._on_click_clear_log,
            width=84,
            height=30,
            corner_radius=8,
            fg_color=CLEAR_BG,
            hover_color=CLEAR_HOVER,
            text_color=CLEAR_TEXT,
            border_width=1,
            border_color=BORDER,
            font=("Microsoft YaHei UI", 10, "bold"),
            cursor="hand2",
            anchor="center",
        )
        self.btn_clear_log.pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_inner,
            height=200,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
            fg_color=RAISED,
            text_color=TEXT_PRIMARY,
            scrollbar_button_color="#383845",
            scrollbar_button_hover_color="#4B4B5B",
            font=("Consolas", 11),
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Bottom utility bar (pinned to surface BOTTOM, NEVER inside _body)
    # ------------------------------------------------------------------
    def _build_util_bar(self) -> None:
        self._util = tk.Frame(self._surface, bg=BG_BASE, highlightthickness=0)
        # Starter dimensions — _reflow_util corrects within ~20 ms after
        # the first <Configure>.
        self._util.place(x=self._pad, y=0, width=680,
                         height=self._util_row_height,
                         anchor="sw", relx=0, rely=1.0)

        self.btn_open_workspace = ctk.CTkButton(
            self._util,
            text="📂  打开工作目录",
            command=open_workspace_folder,
            height=40,
            corner_radius=12,
            fg_color=UTIL_BG,
            hover_color=UTIL_HOVER,
            text_color=UTIL_TEXT,
            border_width=1,
            border_color=BORDER,
            font=("Microsoft YaHei UI", 11, "bold"),
            cursor="hand2",
            anchor="center",
        )
        self.btn_open_workspace.pack(side="left", expand=True, fill="x", padx=(0, 8))

        self.btn_open_logs = ctk.CTkButton(
            self._util,
            text="📋  查看日志文件夹",
            command=self._on_click_open_logs_folder,
            height=40,
            corner_radius=12,
            fg_color=UTIL_BG,
            hover_color=UTIL_HOVER,
            text_color=UTIL_TEXT,
            border_width=1,
            border_color=BORDER,
            font=("Microsoft YaHei UI", 11, "bold"),
            cursor="hand2",
            anchor="center",
        )
        self.btn_open_logs.pack(side="left", expand=True, fill="x", padx=(8, 0))

    # ------------------------------------------------------------------
    # Status chip re-creator (swaps colours on state transitions)
    # ------------------------------------------------------------------
    def _ensure_chip(self, state: str) -> None:
        if state not in STATUS_CHIP:
            # Guard against unknown state strings — keep prior chip.
            return
        text, dot, bg, tc, _ = STATUS_CHIP[state]
        # If chip already exists and colors match, just update text & skip
        if (self._chip_bg is not None and
            self._chip_dot is not None and
            self._chip_text is not None):
            try:
                self._chip_bg.configure(fg_color=bg, border_color=_mix(bg, dot, 0.55))
                self._chip_dot.configure(bg=bg, fg=dot, text="●")
                self._chip_text.configure(bg=bg, fg=tc, text=text)
                return
            except Exception:
                pass
        # (Re)build chip
        for w in self._chip_holder.winfo_children():
            try: w.destroy()
            except Exception: pass
        self._chip_bg = ctk.CTkFrame(
            self._chip_holder,
            fg_color=bg,
            corner_radius=999,
            border_width=1,
            border_color=_mix(bg, dot, 0.55),
            height=34,
        )
        self._chip_bg.pack(side="left")
        # CENTRED pill: dot + text share the same vertical/horizontal anchor
        # so "● 未启动" sits dead-centre inside the rounded rectangle
        # (asymmetric padx=(10,2)/(2,14) → symmetric 10/12 for balance).
        self._chip_dot = tk.Label(
            self._chip_bg, text="●", fg=dot, bg=bg,
            font=("Microsoft YaHei UI", 12, "bold"),
            anchor="center",
        )
        self._chip_dot.pack(side="left", padx=(14, 4), pady=6)
        self._chip_text = tk.Label(
            self._chip_bg, text=text, fg=tc, bg=bg,
            font=("Microsoft YaHei UI", 12, "bold"),
            anchor="center",
        )
        self._chip_text.pack(side="left", padx=(4, 14), pady=6)

    # ------------------------------------------------------------------
    # Sync status detail wraplength to status card body width
    # ------------------------------------------------------------------
    def _resize_status_wrap(self, _e=None) -> None:
        try:
            body_w = self.status_card_body.winfo_width()
            if body_w <= 2:
                return
            # body has padx=18 internally (18 left + 18 right)
            wrap = max(200, body_w - 2 * 18 - 4)
            try:
                self.status_detail.configure(wraplength=wrap)
            except Exception:
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Keep util row pinned & body padding in sync on resize.
    # ------------------------------------------------------------------
    def _reflow_util(self, _e=None) -> None:
        try:
            sw = self._surface.winfo_width()
            if sw < 2: return
            util_w = max(10, sw - 2 * self._pad)
            self._util.place_configure(x=self._pad, y=0, width=util_w,
                                       height=self._util_row_height,
                                       anchor="sw", relx=0, rely=1.0)
        except Exception:
            pass
        try:
            self._body.pack_configure(pady=(self._title_h,
                                            self._util_row_height + 18))
        except Exception:
            pass
        self._resize_status_wrap()

    # =================================================================
    #  Engine callbacks (thread-safe via queue)
    # =================================================================
    def _on_engine_ready(self, port: int, url: str) -> None:
        self._q.put(("ready", (port, url)))

    def _on_engine_state(self, state: EngineState) -> None:
        self._q.put(("state", state))

    def _on_engine_log(self, line: str) -> None:
        self._q.put(("log", line))

    # =================================================================
    #  Tick (30 FPS event clock)
    # =================================================================
    def _tick(self) -> None:
        try:
            self._tw.tick()
        except Exception:
            pass
        # Drain log/state/ready queue
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "state":
                    # IMPORTANT — EngineState is a plain namespace class, NOT an
                    # Enum / str subclass. The engine hands back the plain
                    # string EngineState.RUNNING == "running" etc. Using
                    # `EngineState(str(payload))` would create a new EMPTY
                    # class instance (invalid key) and silently KeyError
                    # inside STATUS_CHIP — which the outer try/except would
                    # swallow, leaving the chip forever "未启动" and buttons
                    # permanently disabled. This was the user's reported
                    # "logs work but state never flips" root cause.
                    state_str = str(payload)
                    self._apply_state(state_str)
                elif kind == "ready":
                    port, url = payload
                    self._append_log(
                        "[ready] Web UI 监听端口 %s — 正在自动打开浏览器…" % (port,))
        except queue.Empty:
            pass
        except Exception:
            pass
        self.after(33, self._tick)

    # =================================================================
    #  State application (affects chips, labels, button states, text)
    # =================================================================
    def _apply_state(self, state: str) -> None:
        if state not in STATUS_CHIP:
            return
        self._state = state
        text, dot, chip_bg, tc, card_bg = STATUS_CHIP[state]
        # Ensure card surface matches desired state card_bg (always SURFACE in
        # this revert — keeps card stable, avoids recolour bugs; chip changes).
        try:
            self.status_card_body.configure(fg_color=card_bg,
                                            border_color=BORDER)
            for child in (self.status_label, self.status_detail,
                          self._chip_holder):
                try: child.configure(bg=card_bg)
                except Exception: pass
        except Exception:
            pass
        self._ensure_chip(state)

        # Status headline
        label_map = {
            EngineState.STOPPED:  "引擎已停止，点击下方按钮启动。",
            EngineState.STARTING: "引擎正在启动，预计 20–40 秒后 Web UI 就绪……",
            EngineState.RUNNING:  "引擎运行中，已自动打开浏览器 Web UI。",
            EngineState.ERROR:    "引擎异常退出，请查看下方日志排查。",
        }
        try:
            self.status_label.configure(text=label_map.get(state, ""))
        except Exception:
            pass

        # Fade in status detail with engine URL when RUNNING
        detail_new = ""
        if state == EngineState.RUNNING:
            url = self.engine.web_url() or ""
            detail_new = "访问地址：%s" % url if url else ""
        elif state == EngineState.STARTING:
            detail_new = "监听端口：%s — 正在分配 token…" % (self.engine.port or "3080")
        elif state == EngineState.ERROR:
            detail_new = "错误详情请查看日志；常见原因：端口被占用或 Node.js 便携环境损坏。"
        else:
            detail_new = "启动后将在此处显示本地 Web UI 访问地址与状态。"

        # Apply detail + colour fade-in for RUNNING
        try:
            self.status_detail.configure(text=detail_new, fg=TEXT_MUTED)
        except Exception:
            pass
        if state == EngineState.RUNNING and detail_new:
            self._fade_detail_text(TEXT_MUTED, TEXT_SECOND, 280)

        # Buttons state mapping
        btn_state = lambda _st, ok: (tk.NORMAL if ok else tk.DISABLED)
        try:
            self.btn_start.configure(
                state=btn_state("start", state == EngineState.STOPPED or
                                       state == EngineState.ERROR))
            self.btn_stop.configure(
                state=btn_state("stop",  state in (EngineState.STARTING,
                                                   EngineState.RUNNING)))
            self.btn_open.configure(
                state=btn_state("open",  state == EngineState.RUNNING))
        except Exception:
            pass

    def _fade_detail_text(self, from_c: str, to_c: str, dur_ms: int = 260) -> None:
        def upd(t, me=self, a=from_c, b=to_c):
            try:
                me.status_detail.configure(fg=_mix(a, b, t))
            except Exception:
                pass
        self._tw.tween(duration_ms=dur_ms, on_update=upd,
                       easing=_ease_out_cubic, delay_ms=40)

    # =================================================================
    #  Button handlers
    # =================================================================
    def _on_click_start(self):
        try: self.engine.start()
        except Exception as e:
            self._append_log("[start] 启动失败：%s" % e)

    def _on_click_stop(self):
        try: self.engine.stop(timeout=3)
        except Exception as e:
            self._append_log("[stop] 停止失败：%s" % e)

    def _on_click_open_browser(self):
        try: self.engine.open_browser()
        except Exception as e:
            self._append_log("[open] 打开浏览器失败：%s" % e)

    def _on_click_open_logs_folder(self):
        open_logs_folder()

    def _on_click_clear_log(self):
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
        finally:
            self.log_box.configure(state="disabled")

    # =================================================================
    #  Log append (2000 line cap, trim tail if exceeded)
    # =================================================================
    def _append_log(self, line: str) -> None:
        if not line:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        content = "[%s] %s\n" % (ts, line)
        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", content)
            # 2000 line cap — trim earliest lines if exceeded
            try:
                count = int(self.log_box.index("end-1c").split(".")[0])
                if count > 2200:
                    self.log_box.delete("1.0", f"{count - 2000}.0")
            except Exception:
                pass
            self.log_box.see("end")
        finally:
            try:
                self.log_box.configure(state="disabled")
            except Exception:
                pass

    # =================================================================
    #  Entrance fade + close flow (WITH FAILSAFE so X always works)
    # =================================================================
    def _do_entrance_fade(self) -> None:
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            return

        def upd(t, me=self):
            try: me.attributes("-alpha", min(1.0, 0.0 + float(t)))
            except Exception: pass

        def done(me=self):
            try: me.attributes("-alpha", 1.0)
            except Exception: pass
        self._tw.tween(duration_ms=300, on_update=upd, on_done=done,
                       easing=_ease_out_cubic, delay_ms=20)

    def _on_close(self):
        if self.engine.is_running_or_starting():
            self._ask_before_close()
        else:
            self._do_close_fade_and_destroy(self.destroy)

    def _do_close_fade_and_destroy(self, after_cb: Callable[[], None]):
        """Fade out 220 ms + FAILSAFE at 320 ms (hard destroy)."""
        called = {"v": False}

        def call_once(_reason: str):
            if called["v"]:
                return
            called["v"] = True
            try:
                self.protocol("WM_DELETE_WINDOW", lambda: None)
            except Exception:
                pass
            try:
                after_cb()
            except Exception:
                # Last-ditch Tk quit
                try:
                    self.after(40, lambda: (tk._default_root.quit()
                                            if getattr(tk, "_default_root", None)
                                            else None))
                except Exception:
                    pass

        try:
            self.attributes("-alpha", 1.0)
        except Exception:
            call_once("attributes-failed")
            return

        def upd(t):
            try: self.attributes("-alpha", max(0.0, 1.0 - float(t)))
            except Exception: pass

        def done(_=None):
            try: self.attributes("-alpha", 0.0)
            except Exception: pass
            call_once("tweener-done")

        try:
            self._tw.tween(duration_ms=220, on_update=upd, on_done=done,
                           easing=_ease_in_out_cubic)
        except Exception:
            call_once("tweener-throw")

        # HARD FAILSAFE — always close within 320 ms.
        try:
            self.after(320, lambda: call_once("after-failsafe"))
        except Exception:
            call_once("after-throw")

    def _ask_before_close(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("确认退出")
        dlg.geometry("460x200")
        dlg.configure(fg_color=SURFACE)
        # Tk dlg entrance fade: 0 -> 1
        try: dlg.attributes("-alpha", 0.0)
        except Exception: pass
        dlg.transient(self)
        dlg.grab_set()
        # Center dlg on top of app
        try:
            sw = self.winfo_width()
            sh = self.winfo_height()
            sx = self.winfo_rootx()
            sy = self.winfo_rooty()
            x = sx + max(0, (sw - 460) // 2)
            y = sy + max(0, (sh - 200) // 2)
            dlg.geometry(f"460x200+{x}+{y}")
        except Exception:
            pass

        ctk.CTkLabel(
            dlg,
            text="引擎仍在运行中\n关闭窗口时是否同时停止引擎？",
            text_color=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 14),
            justify="center",
        ).pack(pady=(30, 18), padx=20)

        row = ctk.CTkFrame(dlg, fg_color=SURFACE, corner_radius=0)
        row.pack(pady=(0, 20))

        def stop_and_exit():
            dlg.destroy()
            try: self.engine.stop(timeout=3)
            except Exception: pass
            self._do_close_fade_and_destroy(self.destroy)

        def just_exit():
            dlg.destroy()
            # Leave engine running on user's choice — just close GUI.
            self._do_close_fade_and_destroy(self.destroy)

        ctk.CTkButton(
            row, text="停止引擎并退出",
            fg_color=DANGER, hover_color=DANGER_HOVER,
            text_color=DANGER_TEXT,
            height=40, corner_radius=12,
            border_width=1, border_color=_mix(DANGER, "#000000", 0.25),
            font=("Microsoft YaHei UI", 12, "bold"),
            cursor="hand2",
            command=stop_and_exit,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            row, text="仅关闭 GUI",
            fg_color=UTIL_BG, hover_color=UTIL_HOVER,
            text_color=UTIL_TEXT,
            height=40, corner_radius=12,
            border_width=1, border_color=BORDER,
            font=("Microsoft YaHei UI", 12, "bold"),
            cursor="hand2",
            command=just_exit,
        ).pack(side="left", padx=(10, 0))

        # Fade in dlg after short delay
        try:
            def _fade_in_dlg(t, d=dlg):
                try: d.attributes("-alpha", min(1.0, float(t)))
                except Exception: pass
            self._tw.tween(duration_ms=180, on_update=_fade_in_dlg,
                           easing=_ease_out_cubic, delay_ms=40)
        except Exception:
            try: dlg.attributes("-alpha", 1.0)
            except Exception: pass


# =============================================================================
#  Main entry (launched via start.bat pythonw)
# =============================================================================

def main() -> int:
    app = LauncherApp()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
