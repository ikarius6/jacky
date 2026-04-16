# -*- coding: utf-8 -*-
"""debug_windows.py — list all windows the pet can see.

Run from the project root (venv activated):
    python debug_windows.py

Columns:
  HWND      — native window handle (hex)
  STATE     — maximized / normal
  RECT      — (left, top, right, bottom) in physical pixels
  SIZE      — width × height
  JUNK?     — Y if the pet ignores this window, N if it's "interesting"
  PROCESS   — executable name
  TITLE     — window title
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import os

# Allow running from repo root without installing the package.
sys.path.insert(0, os.path.dirname(__file__))

from pal import get_visible_windows, get_foreground_window
from interaction.window_awareness import _is_junk_window

# ── ANSI colours (work in Windows Terminal / PowerShell 7) ──────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_DIM    = "\033[2m"


def _state(w) -> str:
    if w.is_maximized:
        return "MAXIMIZED"
    return "normal    "


def _junk_tag(w) -> str:
    return f"{_RED}Y{_RESET}" if _is_junk_window(w.title, w.process_name) else f"{_GREEN}N{_RESET}"


def main():
    print(f"\n{_BOLD}{_CYAN}=== Jacky — visible windows debug ==={_RESET}\n")

    windows = get_visible_windows()
    fg = get_foreground_window()

    if not windows:
        print(f"{_RED}No windows found.{_RESET}")
        return

    # ── Header ──────────────────────────────────────────────────────────────
    col_w = {
        "hwnd":    10,
        "state":   10,
        "rect":    34,
        "size":    14,
        "junk":     6,
        "proc":    24,
        "title":   50,
    }

    def header_cell(label, width):
        return f"{_BOLD}{label:<{width}}{_RESET}"

    header = (
        header_cell("HWND",    col_w["hwnd"])
        + header_cell("STATE",   col_w["state"])
        + header_cell("RECT",    col_w["rect"])
        + header_cell("SIZE",    col_w["size"])
        + header_cell("JUNK?",   col_w["junk"])
        + header_cell("PROCESS", col_w["proc"])
        + header_cell("TITLE",   col_w["title"])
    )
    sep = "-" * sum(col_w.values())

    print(header)
    print(sep)

    interesting = [w for w in windows if not _is_junk_window(w.title, w.process_name)]
    junk        = [w for w in windows if     _is_junk_window(w.title, w.process_name)]

    for w in interesting + junk:
        is_fg    = fg and w.hwnd == fg.hwnd
        title    = w.title[:col_w["title"] - 1]
        proc     = w.process_name[:col_w["proc"] - 1]
        rect_str = f"({w.left:5},{w.top:5},{w.right:5},{w.bottom:5})"
        size_str = f"{w.width}×{w.height}"
        hwnd_str = f"0x{w.hwnd:08X}"

        fg_mark  = f" {_YELLOW}<< FG{_RESET}" if is_fg else ""
        row_col  = _DIM if _is_junk_window(w.title, w.process_name) else ""

        row = (
            f"{row_col}"
            f"{hwnd_str:<{col_w['hwnd']}}"
            f"{_state(w):<{col_w['state']}}"
            f"{rect_str:<{col_w['rect']}}"
            f"{size_str:<{col_w['size']}}"
            f"{_RESET}"        # reset before junk colour
            + _junk_tag(w)
            + f" " * (col_w["junk"] - 2)
            + f"{row_col}"
            + f"{proc:<{col_w['proc']}}"
            + f"{title}"
            + f"{_RESET}"
            + fg_mark
        )
        print(row)

    print(sep)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n  Total windows seen  : {_BOLD}{len(windows)}{_RESET}")
    print(f"  Interesting (pet uses): {_BOLD}{_GREEN}{len(interesting)}{_RESET}")
    print(f"  Filtered as junk      : {_BOLD}{_DIM}{len(junk)}{_RESET}")
    if fg:
        print(f"  Foreground window     : {_YELLOW}{fg.title!r}{_RESET} ({fg.process_name})")
    print()


if __name__ == "__main__":
    main()
