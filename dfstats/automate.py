"""Game-client automation: drive 三角洲行动 to look up a player by ID and snap
the 4 profile screens, then return their paths so the existing OCR pipeline can
ingest them.

Design choices to reduce anti-cheat signature/behavioural risk:
* No process injection, no memory reads — pure OS-level input + desktop capture.
* Pixel positions are not hard-coded and (almost) no manual calibration is
  needed. Most controls in the flow are Chinese **text** labels (加好友 / 个人信息
  / 详细数据 / 数据总览 / 排位赛数据 / 历史战绩), so at run time the bot screenshots
  the live game, OCRs the whole frame with the already-installed RapidOCR, finds
  the on-screen text of the control it wants and clicks its centre. A cropped
  reference image (`cv2.matchTemplate`) is only an **optional fallback** for the
  rare control that has no text (e.g. the search box / the first result row).
* Every action is wrapped in a gaussian-randomised pause; mouse moves use a
  curved tween with tiny per-step jitter; keystrokes have variable spacing.
  The bot will look mechanical to a careful observer but should not stick out
  on simple timing heuristics.
* Failsafe: pyautogui.FAILSAFE remains TRUE — slamming the mouse into a screen
  corner aborts the script instantly.

The bot is NOT a guarantee against bans. The user has been told.
"""
from __future__ import annotations
import os
import time
import random
import string
import re
import difflib
import subprocess
import threading
import ctypes
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import pyautogui
from mss import mss

from . import imgio, ocr

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0  # we do our own pauses
# pyautogui silently TELEPORTS the cursor when duration < MINIMUM_DURATION
# (default 0.1s) — maximally robotic for short hops. Lower the floor so even a
# 60ms flick still tweens along a path like a human wrist movement.
pyautogui.MINIMUM_DURATION = 0.02
pyautogui.MINIMUM_SLEEP = 0.005

# DPI awareness: with Windows display scaling != 100% an unaware process sees
# VIRTUALIZED coordinates while mss grabs PHYSICAL pixels — every OCR hit would
# click offset by the scale factor on such machines. pyautogui already sets
# legacy system-DPI awareness on import; upgrading to per-monitor-v2 also keeps
# mixed-DPI multi-monitor setups consistent. Best-effort, never fatal.
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


# =============================== cancellation ===============================
# A cooperative STOP: the UI's 停止 button sets this event; the running lookup
# polls it at every step boundary and at the top of each wait/poll loop, raising
# LookupCancelled so the worker can abandon the query cleanly (vs. pyautogui's
# mouse-to-corner FAILSAFE, which is a panic abort, not a graceful one). The
# event is process-global because there is only ever one lookup running at a time
# (jobs.py runs a single worker thread).
_CANCEL = threading.Event()


class LookupCancelled(Exception):
    """Raised inside run_auto_lookup when a stop was requested."""


def request_cancel() -> None:
    """Ask the in-flight lookup to stop at its next checkpoint."""
    _CANCEL.set()


def clear_cancel() -> None:
    """Reset the stop flag before starting a new lookup."""
    _CANCEL.clear()


def cancel_requested() -> bool:
    return _CANCEL.is_set()


def _ck() -> None:
    """Checkpoint: raise if a stop was requested. Sprinkled at step boundaries
    and at the top of every polling loop so a stop takes effect within ~0.2s."""
    if _CANCEL.is_set():
        raise LookupCancelled()


# ---- step names used in progress callbacks (kept stable for UI/tests) -----
# Real flow (from the user's screenshots P1-P4):
#   P1 首页  → click the social/friends icon on the bottom bar (icon, no text)
#   P2 社交  → click "添加好友" (text button, top-right)
#   P3 添加好友 → type ID in the search box → search → click the result avatar
#               → click "信息" in the popup
#   P4 角色信息 → 个人信息 / 详细数据(数据总览·排位赛数据) / 历史战绩 三个 tab,逐个截图
STEPS = (
    "open_social",      # 首页点社交/好友图标
    "open_add_friend",  # 点「添加好友」
    "type_id",          # 输入 ID/昵称
    "search",           # 回车/点搜索
    "open_result",      # 点搜索结果头像
    "open_info",        # 点「信息」进角色信息
    "tab_profile",      # 个人信息 → 截图(home)
    "tab_details",      # 详细数据 默认数据总览 → 截图(overview)
    "switch_ranked",    # 下拉切排位赛数据 → 截图(ranked)
    "tab_history",      # 历史战绩 → 截图(recent)
    "return_home",      # Esc 退回主页
)

# Optional template names. The bot locates controls by OCR text first; a cropped
# reference PNG in <calib_dir>/<name>.png is only used as a fallback. With the
# real UI almost everything is text — only the home-screen social icon has none,
# and it falls back to a fixed bottom-bar fraction (SOCIAL_ICON_FRAC) so even
# that needs no calibration by default.
TEMPLATES = (
    "social_icon",       # the friends/social icon on the home bottom bar (icon)
    "add_friend_btn",    # the "添加好友" button (text)
    "friend_search_box", # the search input box in the add-friend dialog
    "first_result",      # the first search result row / avatar
    "open_info",         # the "信息" button in the result popup (text)
    "tab_profile",       # "个人信息" tab
    "tab_details",       # "详细数据" tab
    "dropdown_mode",     # the mode dropdown ("数据总览")
    "dropdown_ranked",   # the "排位赛数据" option
    "tab_history",       # "历史战绩" tab
)

# OCR auto-location: the on-screen Chinese text for each control. The bot reads
# the whole frame and clicks the best-matching token, so these need no calibration.
# Each value is a list of acceptable strings (first = canonical, rest = aliases /
# common OCR slips). Controls absent here have no stable text → positional/fallback.
TEXT_CONTROLS: dict[str, list[str]] = {
    "add_friend_btn":  ["添加好友"],
    "open_info":       ["信息"],
    "tab_profile":     ["个人信息"],
    "tab_details":     ["详细数据"],
    "dropdown_mode":   ["数据总览"],
    "dropdown_ranked": ["排位赛数据", "排位赛"],
    "tab_history":     ["历史战绩"],
}

# The add-friend search box placeholder (P3). Best-effort anchors; if none are
# found the bot just types (the dialog usually focuses the box on open).
SEARCH_PLACEHOLDERS = ["请输入ID或玩家昵称", "请输入", "玩家昵称", "搜索玩家名或UID",
                       "昵称或UID", "搜索玩家", "昵称/ID"]

# Where each control lives, as a (x0,y0,x1,y1) fraction of the frame. OCR cost is
# dominated by the NUMBER of text boxes RapidOCR has to recognise (~54 on a full
# 2560x1440 frame → 3-7s even downscaled), so we OCR only this sub-rectangle and
# the box count (hence time) collapses. Measured live: the 个人信息/详细数据/历史战绩
# tabs sit in the top strip at y~0.07, x 0.10-0.24. Padding is added on top, and
# locate_text still does a precise containment check, so a generous box is safe.
# Controls without an entry fall back to full-frame OCR (still downscaled).
CONTROL_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "tab_profile": (0.0, 0.0, 0.45, 0.16),
    "tab_details": (0.0, 0.0, 0.45, 0.16),
    "tab_history": (0.0, 0.0, 0.45, 0.16),
    # 社交→添加好友 used to stall for seconds: the friend list is ~40 text boxes
    # and full-frame OCR had to recognise them all every poll. The green 添加好友
    # button sits top-right at frac ~(0.91,0.16), so cropping there cuts the boxes
    # to a handful and the poll is near-instant.
    "add_friend_btn": (0.74, 0.08, 1.0, 0.26),
}

# The home-screen social/friends icon has no text. Default click point as a
# fraction of the screen. Measured live on the real client (2560x1440): the
# two-silhouette friends icon (with the online-friends count beside it) sits in
# the bottom bar at px ~(2135,1400) -> (0.834,0.972). The green 行前备战 button
# is ~90px above this, so the vertical gap is safe. Override by calibrating a
# 'social_icon.png' template.
SOCIAL_ICON_FRAC = (0.834, 0.972)

# The add-friend dialog's SEARCH trigger is a magnifier ICON (no text) at the
# right end of the box. Pressing Enter does NOT search in this client, so we
# click this fixed point. Measured live (2560x1440): px ~(1987,446). The X
# (clear) button is ~60px to its left — keep clear of it.
SEARCH_BTN_FRAC = (0.776, 0.310)

# The add-friend search BOX itself (click to focus before typing). Its
# placeholder is low-contrast grey that OCR can't read, so we must NOT rely on
# locating it by text — we click a fixed fraction. Same row as the magnifier;
# the box centre sits well to its left. Measured live (2560x1440): px ~(1395,446).
SEARCH_BOX_FRAC = (0.545, 0.310)

# In a search-result row the clickable target is the player AVATAR on the left;
# clicking the name TEXT does nothing. The avatar centre sits just left of the
# name token's left edge and a little lower. Offsets are applied to the matched
# name token (left edge x, centre y).
RESULT_AVATAR_DX = -25   # px left of the name token's left edge
RESULT_AVATAR_DY = 22    # px below the name token's centre
# The avatar COLUMN of the add-friend results list, as a frame-width fraction
# (live-measured: avatar spans x 0.333-0.365, centre 0.348). Used for 编号/UID
# queries, where the row shows a nickname we can't match against the query.
RESULT_AVATAR_X_FRAC = 0.348

# The player-card popup's 信息 button is icon-over-label and only the ICON is
# clickable; the text label below it is dead. The icon centre is ~50px above the
# "信息" text token (measured at 1440p; rescaled live).
INFO_ICON_DY = -50

# Where the popup's 信息/屏蔽 button row lives (fraction of frame). The popup is
# anchored to the first search result (a fixed position), so this band is stable.
# 信息 is a small label the fast engine drops on the full frame, so open_info_popup
# OCRs just this band with the accurate engine.
INFO_POPUP_REGION = (0.18, 0.48, 0.62, 0.68)


# ============================== humanise input ==============================

def _gauss_pause(mu: float = 0.35, sigma: float = 0.13, lo: float = 0.12, hi: float = 1.6) -> None:
    t = random.gauss(mu, sigma)
    time.sleep(max(lo, min(hi, t)))


# Global pace for the *deliberate* between-step waits (NOT the micro-jitter
# inside a single click/keystroke). The user wants 快准狠 and accepts the higher
# detection risk, so this runs well below 1.0. Raise toward 1.0 to look more
# human (slower); lower toward 0 for maximum speed.
PACE = 0.3

# Control-location OCR uses the fast engine (ocr.get_fast_engine): det_limit_type
# 'max' + angle-cls off, ~2-3x faster with no big-text accuracy loss. That engine's
# long-side cap already shrinks the detector input, so we feed it at full res
# (scale 1.0) — extra pre-downscaling only risks legibility for no real speed gain.
# The real per-call savings come from (a) the fast engine and (b) cropping to the
# control's region (CONTROL_REGIONS / _ocr_region) so RapidOCR recognises a handful
# of boxes instead of ~54.
CONTROL_OCR_SCALE = 1.0


def _settle(mu: float, sigma: Optional[float] = None) -> None:
    """A deliberate between-step wait, scaled by the global PACE multiplier."""
    if sigma is None:
        sigma = mu * 0.30
    time.sleep(max(0.04, random.gauss(mu * PACE, sigma * PACE)))


def _human_move(x: int, y: int) -> None:
    """Move cursor to ABSOLUTE (x,y) like a practised human flick: duration grows
    sub-linearly with distance (Fitts-ish) so short hops are near-instant
    (~60-80ms) and a cross-screen move stays ~200ms — fast but never a teleport.
    A ±2px target jitter keeps identical clicks from repeating pixel-exactly."""
    cx, cy = pyautogui.position()
    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    # tuned down twice at the user's request: clicks are the top speed priority.
    # short hops ~30-50ms, full cross-screen ~110ms — brisk but still a tween.
    dur = 0.028 + 0.062 * (dist / 1000.0) ** 0.6
    dur = max(0.025, min(0.16, random.gauss(dur, dur * 0.18)))
    tx = x + random.randint(-2, 2)
    ty = y + random.randint(-2, 2)
    pyautogui.moveTo(tx, ty, duration=dur, tween=pyautogui.easeInOutQuad)


def click_at(x: int, y: int) -> None:
    """Click a point given in FRAME (game-window) coordinates."""
    sx, sy = _to_screen(x, y)
    _human_move(sx, sy)
    _gauss_pause(0.025, 0.012, 0.012, 0.06)
    pyautogui.click()
    _settle(0.12)


def _type_via_keys(text: str, mu: float = 0.045, sigma: float = 0.022) -> None:
    for ch in text:
        pyautogui.write(ch, interval=0)
        time.sleep(max(0.02, random.gauss(mu, sigma)))


def _set_clipboard_text(text: str) -> bool:
    """Set the clipboard via the Win32 API directly (~1ms). The old PowerShell
    Set-Clipboard spawn cost ~0.5-1s of pure dead time per query. Returns False
    on any failure so the caller can fall back. We deliberately do NOT
    save/restore the user's previous clipboard (speed wins); the query nickname
    is simply left on the clipboard afterwards."""
    CF_UNICODETEXT, GHND = 13, 0x0042
    try:
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        data = text.encode("utf-16-le") + b"\x00\x00"
        for _ in range(8):              # the clipboard is a contended global
            if user32.OpenClipboard(0):
                break
            time.sleep(0.02)
        else:
            return False
        try:
            user32.EmptyClipboard()
            h = kernel32.GlobalAlloc(GHND, len(data))
            if not h:
                return False
            p = kernel32.GlobalLock(h)
            if not p:
                kernel32.GlobalFree(h)
                return False
            ctypes.memmove(p, data, len(data))
            kernel32.GlobalUnlock(h)
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)
                return False
        finally:
            user32.CloseClipboard()
        return True
    except Exception:
        return False


def _type_via_clipboard(text: str) -> None:
    """Clipboard + Ctrl+V (for CJK / anything outside printable ASCII)."""
    if not _set_clipboard_text(text):
        subprocess.run(   # last-resort fallback: slow (~1s) but battle-tested
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value {repr(text)}"],
            timeout=3, check=False,
        )
    _gauss_pause(0.06, 0.03)
    pyautogui.hotkey("ctrl", "v")
    _gauss_pause(0.12, 0.05)


def type_text(text: str) -> None:
    """Type `text` into the focused field, humanised. Falls back to clipboard
    paste when the text isn't plain ASCII (for CJK nicknames)."""
    text = str(text)
    if all(ch in string.printable and ord(ch) < 128 for ch in text):
        _type_via_keys(text)
    else:
        _type_via_clipboard(text)


def press(key: str) -> None:
    pyautogui.press(key)
    _gauss_pause(0.10, 0.04)


# =============================== screen + cv ================================
# --------- game-window anchoring (resolution / monitor adaptation) ----------
# Everything the bot reads and clicks is expressed in coordinates of the GAME
# WINDOW's client area, not the whole desktop: grab_screen() captures that rect
# and click_at() maps frame coords back to absolute screen pixels (_to_screen).
# On a fullscreen-primary setup this is identical to grabbing the monitor, but
# it ALSO makes borderless/windowed mode, a game moved to another monitor, and
# any other resolution work unchanged: the fractions in CONTROL_REGIONS and
# *_FRAC are resolution-independent by construction, and the few hand-measured
# PIXEL offsets are rescaled from the 1440p reference by the live frame height.

_GAME_RECT: Optional[dict] = None
_REF_FRAME_H = 1440.0    # height all hand-measured pixel offsets were taken at


class _W32RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _W32POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _find_game_window() -> Optional[tuple[int, str]]:
    """(hwnd, title) of the visible 三角洲行动 / Delta Force window, or None."""
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return None
    hits: list[tuple[int, str]] = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    # The window TITLE must be the actual game ("三角洲行动" / "Delta Force"),
    # not just "三角洲"/"Delta" — our own web app's browser tab is titled
    # "三角洲 · 战绩分析器", so a loose match was grabbing the BROWSER (or another
    # foreground window) instead of the game and driving/grabbing the wrong window.
    _BROWSER_MARKS = ("战绩分析器", "DELTASTATS", "Edge", "Chrome", "Firefox",
                      "Mozilla", "Visual Studio")

    def _cb(hwnd, _l):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                v = buf.value
                if ("三角洲行动" in v or "Delta Force" in v) and not any(
                        b in v for b in _BROWSER_MARKS):
                    hits.append((hwnd, v))
        return True

    try:
        user32.EnumWindows(EnumProc(_cb), 0)
    except Exception:
        return None
    return hits[0] if hits else None


def refresh_game_rect() -> Optional[dict]:
    """Re-measure the game client area (called after focusing). Falls back to
    None (= grab the whole primary monitor) when it can't be measured."""
    global _GAME_RECT
    _GAME_RECT = None
    hit = _find_game_window()
    if hit is None:
        return None
    try:
        user32 = ctypes.windll.user32
        rc = _W32RECT()
        if not user32.GetClientRect(hit[0], ctypes.byref(rc)):
            return None
        pt = _W32POINT(0, 0)
        if not user32.ClientToScreen(hit[0], ctypes.byref(pt)):
            return None
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w < 640 or h < 480:           # minimised / still restoring
            return None
        _GAME_RECT = {"left": int(pt.x), "top": int(pt.y), "width": int(w), "height": int(h)}
    except Exception:
        _GAME_RECT = None
    return _GAME_RECT


def _to_screen(x: int, y: int) -> tuple[int, int]:
    """Frame (game-window) coords → absolute desktop coords for the mouse."""
    r = _GAME_RECT
    if r:
        return x + r["left"], y + r["top"]
    return x, y


def _frame_size() -> tuple[int, int]:
    """(width, height) of the coordinate space frames are grabbed in."""
    r = _GAME_RECT
    if r:
        return r["width"], r["height"]
    w, h = pyautogui.size()
    return int(w), int(h)


def grab_screen(region: Optional[dict] = None) -> np.ndarray:
    """Fast desktop capture → BGR ndarray. Defaults to the GAME window's client
    rect when one was measured (refresh_game_rect), else the primary monitor.
    `region` is an mss-style dict {top, left, width, height}."""
    with mss() as s:
        mon = region or _GAME_RECT or s.monitors[1]
        img = np.array(s.grab(mon))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def save_image(img: np.ndarray, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    imgio.imwrite(path, img)        # unicode-safe: the exe may live in a CJK dir
    return path


def _ocr_region(scr: np.ndarray, region: tuple[float, float, float, float],
                scale: float, pad: float = 0.02, fast: bool = True) -> list[dict]:
    """OCR only a fractional sub-rectangle of the frame, returning tokens in
    FULL-frame pixel coords. This is the main speed lever: RapidOCR's cost scales
    with the number of detected text boxes, so cropping to where a control lives
    (a handful of boxes) is far faster than OCRing the whole frame (~54 boxes).
    `scale` is still applied to the crop. A small pad guards against clipping a
    glyph at the region edge. `fast=False` uses the accurate engine — needed for
    small labels (e.g. the popup's 信息 button) the fast engine downscales away."""
    H, W = scr.shape[:2]
    x0, y0, x1, y1 = region
    px0 = max(0, int((x0 - pad) * W)); py0 = max(0, int((y0 - pad) * H))
    px1 = min(W, int((x1 + pad) * W)); py1 = min(H, int((y1 + pad) * H))
    if px1 <= px0 or py1 <= py0:
        return []
    toks = ocr.ocr_image(scr[py0:py1, px0:px1], scale=scale, fast=fast)
    for t in toks:                       # crop space → full-frame space
        t["x"] += px0; t["x2"] += px0
        t["y"] += py0; t["y2"] += py0
    return toks


def _wait_stable(max_wait: float = 0.8, gap: float = 0.07, thresh: float = 2.0) -> np.ndarray:
    """Grab frames until two consecutive ones are ~identical (the UI has finished
    animating) or `max_wait` elapses; return the last frame. OCR-free and cheap,
    so screenshots stay correct (not mid-transition) even with fast pacing. A
    static page settles in one gap; max_wait only bites during a real animation."""
    prev = grab_screen()
    end = time.monotonic() + max_wait
    while time.monotonic() < end:
        time.sleep(gap)
        cur = grab_screen()
        if prev.shape == cur.shape and float(np.mean(cv2.absdiff(prev, cur))) < thresh:
            return cur
        prev = cur
    return prev


def find_template(scr: np.ndarray, tmpl_path: str, threshold: float = 0.82) -> Optional[tuple[int, int]]:
    """Locate a small reference button in the screen. Returns (cx, cy) or None.

    Uses CCOEFF_NORMED which is robust to lighting differences. If your game
    has a different DPR/resolution than when you calibrated, the match may
    fail — recalibrate or rely on multi-scale search below.
    """
    tmpl = imgio.imread(tmpl_path, cv2.IMREAD_COLOR)
    if tmpl is None:
        raise FileNotFoundError(f"模板缺失: {tmpl_path}")
    res = cv2.matchTemplate(scr, tmpl, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _ml, mxl = cv2.minMaxLoc(res)
    if mx < threshold:
        return None
    h, w = tmpl.shape[:2]
    return (mxl[0] + w // 2, mxl[1] + h // 2)


def click_template(name: str, calib_dir: Path, threshold: float = 0.82, scr: Optional[np.ndarray] = None) -> None:
    scr = scr if scr is not None else grab_screen()
    pt = find_template(scr, str(calib_dir / f"{name}.png"), threshold)
    if pt is None:
        raise RuntimeError(f"屏幕上没找到「{name}」按钮（模板匹配失败,可能要重新校准 / 游戏不在前台）")
    click_at(*pt)


def wait_for_template(name: str, calib_dir: Path, timeout: float = 8.0, threshold: float = 0.82) -> tuple[int, int]:
    """Poll the screen until `name` appears or timeout. Returns its center."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _ck()
        scr = grab_screen()
        pt = find_template(scr, str(calib_dir / f"{name}.png"), threshold)
        if pt is not None:
            return pt
        time.sleep(0.12 + random.random() * 0.08)
    raise TimeoutError(f"等待「{name}」出现超时（{timeout:.0f}s）")


# ============================ OCR auto-location =============================

def _norm(s: str) -> str:
    """Strip whitespace/punctuation noise so OCR slips still match candidates."""
    return re.sub(r"[\s·.,:：。、|/\\_-]+", "", str(s or ""))


def _match_score(cand: str, txt: str) -> float:
    """0..1 similarity between a wanted label and an OCR token (both normalised)."""
    if not cand or not txt:
        return 0.0
    if cand == txt:
        return 1.0
    if cand in txt:               # token contains the label (e.g. "个人信息>")
        return 0.92
    if txt in cand and len(txt) >= 2:  # token is a clean prefix of the label
        return 0.82
    return difflib.SequenceMatcher(None, cand, txt).ratio()


def locate_text(
    tokens: list[dict],
    candidates: list[str],
    *,
    region: Optional[tuple[float, float, float, float]] = None,
    scr_shape: Optional[tuple] = None,
    min_ratio: float = 0.74,
) -> Optional[tuple[int, int, dict]]:
    """Find the best on-screen token matching any candidate string.

    `region` (x0,y0,x1,y1 as 0..1 fractions) restricts where to look — useful to
    bias toward the left sidebar for tabs. Returns (cx, cy, token) or None.
    """
    H = W = 1
    if scr_shape is not None:
        H, W = scr_shape[0], scr_shape[1]
    cands = [_norm(c) for c in candidates]
    best: Optional[dict] = None
    best_score = 0.0
    for t in tokens:
        txt = _norm(t.get("text", ""))
        if not txt:
            continue
        if region is not None and scr_shape is not None:
            cx = (t["x"] + t["x2"]) / 2 / W
            cy = (t["y"] + t["y2"]) / 2 / H
            x0, y0, x1, y1 = region
            if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                continue
        score = max(_match_score(c, txt) for c in cands)
        if score > best_score:
            best_score = score
            best = t
    if best is not None and best_score >= min_ratio:
        return ((best["x"] + best["x2"]) // 2, (best["y"] + best["y2"]) // 2, best)
    return None


def _occluded_hint(name: str, timeout: float, how: str, tokens: list[dict]) -> str:
    """Build a self-diagnosing timeout message. The #1 cause of a control not being
    found is NOT bad OCR — it's that an always-on-top window (a browser, a
    notification, another pinned app) is covering the game, so the grab
    OCRs THAT window's text instead of the game. Dumping what we actually saw makes
    this obvious at a glance (e.g. chat/browser words instead of game labels)."""
    seen = "、".join((t.get("text", "") or "").strip() for t in (tokens or [])[:6])
    seen = seen or "（没识别到任何文字）"
    return (
        f"屏幕上没找到「{name}」（OCR{how}定位失败，{timeout:.0f}s 超时）。"
        f"当时该位置识别到的文字是：{seen}。"
        f"如果这些不像游戏内容（像是聊天/浏览器/这段对话的文字），"
        f"说明《三角洲行动》被一个置顶窗口挡住了——请让游戏全屏置顶、"
        f"把浏览器等置顶窗口移开或最小化后再试。"
        f"（无文字的控件也可在校准页补一张参考图兜底）"
    )


def click_control(
    name: str,
    *,
    calib_dir: Optional[Path] = None,
    candidates: Optional[list[str]] = None,
    region: Optional[tuple[float, float, float, float]] = None,
    timeout: float = 8.0,
    threshold: float = 0.82,
    required: bool = True,
) -> Optional[tuple[str, tuple[int, int]]]:
    """Locate a control and click it. OCR text first, calibrated template as
    fallback. Polls until `timeout`. Returns (method, (x,y)) or None.

    required=False → return None instead of raising when nothing is found
    (used for the optional search-box click).
    """
    end = time.monotonic() + timeout
    tmpl_path = Path(calib_dir) / f"{name}.png" if calib_dir else None
    last_tokens: list[dict] = []
    while True:
        _ck()
        scr = grab_screen()
        # 1) OCR text (preferred — needs no calibration). Downscaled for speed,
        #    and cropped to `region` when given (far fewer boxes → much faster).
        if candidates:
            tokens = (_ocr_region(scr, region, CONTROL_OCR_SCALE) if region
                      else ocr.ocr_image(scr, scale=CONTROL_OCR_SCALE, fast=True))
            last_tokens = tokens
            hit = locate_text(tokens, candidates, region=region, scr_shape=scr.shape)
            if hit is not None:
                click_at(hit[0], hit[1])
                return ("ocr", (hit[0], hit[1]))
        # 2) template fallback (only if the user calibrated this one)
        if tmpl_path is not None and tmpl_path.exists():
            pt = find_template(scr, str(tmpl_path), threshold)
            if pt is not None:
                click_at(*pt)
                return ("tmpl", pt)
        if time.monotonic() >= end:
            break
        time.sleep(0.12 + random.random() * 0.08)
    if not required:
        return None
    how = "文字" + ("/模板" if (tmpl_path and tmpl_path.exists()) else "")
    raise RuntimeError(_occluded_hint(name, timeout, how, last_tokens))


def wait_control(
    name: str,
    candidates: list[str],
    *,
    calib_dir: Optional[Path] = None,
    region: Optional[tuple[float, float, float, float]] = None,
    timeout: float = 8.0,
    threshold: float = 0.82,
    min_ratio: float = 0.74,
) -> tuple[int, int]:
    """Poll until a control (by OCR text, or template fallback) is visible.
    Returns its centre. Raises TimeoutError otherwise. Does NOT click.

    `min_ratio` raises the OCR match bar — pass ~0.9 to wait for an EXACT label
    (e.g. the 个人信息 tab) and not trip on a fuzzy partial (the player-card
    popup's 信息 button fuzzy-matches 个人信息 at 0.82)."""
    end = time.monotonic() + timeout
    tmpl_path = Path(calib_dir) / f"{name}.png" if calib_dir else None
    last_tokens: list[dict] = []
    while True:
        _ck()
        scr = grab_screen()
        tokens = (_ocr_region(scr, region, CONTROL_OCR_SCALE) if region
                  else ocr.ocr_image(scr, scale=CONTROL_OCR_SCALE, fast=True))
        last_tokens = tokens
        hit = locate_text(tokens, candidates, region=region, scr_shape=scr.shape, min_ratio=min_ratio)
        if hit is not None:
            return (hit[0], hit[1])
        if tmpl_path is not None and tmpl_path.exists():
            pt = find_template(scr, str(tmpl_path), threshold)
            if pt is not None:
                return pt
        if time.monotonic() >= end:
            seen = "、".join((t.get("text", "") or "").strip() for t in last_tokens[:6]) or "（没识别到文字）"
            raise TimeoutError(f"等待「{name}」出现超时（{timeout:.0f}s）；当时看到：{seen}")
        time.sleep(0.12 + random.random() * 0.08)


def click_first_result(query: str, calib_dir: Path, timeout: float = 8.0) -> tuple[str, tuple[int, int]]:
    """Open the first search result by clicking the player AVATAR.

    Live-verified quirks:
    * the queried name appears twice — in the search box (top) AND the result
      row — so we only look BELOW the search box (region y>0.34);
    * clicking the name TEXT does nothing; the avatar is the hotspot;
    * a NUMERIC query (编号/UID) renders the row with the player's NICKNAME, so
      there is no query text to match — instead we take the top-most token in
      the first-row band and click the fixed avatar COLUMN (RESULT_AVATAR_X_FRAC).
    Falls back to a calibrated `first_result` template."""
    region = (0.0, 0.34, 1.0, 0.95)   # results area, excluding the search-box row
    uid_mode = _norm(str(query)).isdigit()
    row_band = (0.345, 0.335, 0.85, 0.44)   # first result row (nickname + rank line)
    end = time.monotonic() + timeout
    while True:
        _ck()
        scr = grab_screen()
        H, W = scr.shape[:2]
        scl = H / _REF_FRAME_H               # offsets were measured at 1440p
        if uid_mode:
            toks = [t for t in _ocr_region(scr, row_band, 1.0)
                    if _norm(t.get("text", "")) not in ("", "好友搜索", "好友搜素", "申请列表")]
            if toks:
                top = min(toks, key=lambda t: t["y"])          # the nickname line
                ax = int(RESULT_AVATAR_X_FRAC * W)
                ay = (top["y"] + top["y2"]) // 2 + int(RESULT_AVATAR_DY * scl)
                click_at(ax, ay)
                return ("ocr-uid-avatar", (ax, ay))
        else:
            # crop to the results area at FULL res — a CJK nickname needs every
            # pixel to read back at min_ratio 0.8 (downscaling risks a miss).
            tokens = _ocr_region(scr, region, 1.0)
            hit = locate_text(tokens, [query], region=region, scr_shape=scr.shape, min_ratio=0.8)
            if hit is not None:
                tok = hit[2]
                ax = tok["x"] + int(RESULT_AVATAR_DX * scl)   # avatar left of the name
                ay = (tok["y"] + tok["y2"]) // 2 + int(RESULT_AVATAR_DY * scl)
                click_at(ax, ay)
                return ("ocr-avatar", (ax, ay))
        tp = Path(calib_dir) / "first_result.png"
        if tp.exists():
            pt = find_template(scr, str(tp))
            if pt is not None:
                click_at(*pt)
                return ("tmpl", pt)
        if time.monotonic() >= end:
            break
        time.sleep(0.12 + random.random() * 0.08)
    raise RuntimeError(
        "没定位到搜索结果：这个昵称/编号可能搜不到人，或结果行没识别出来——"
        "可在校准页给 first_result 拍一张参考图兜底"
    )


def click_pos_frac(fx: float, fy: float) -> tuple[int, int]:
    """Click a point given as a fraction (0..1) of the GAME FRAME (not the
    desktop — that's what makes these stable across resolutions/monitors).
    Used for the few controls with no OCR-able text (social icon / search box)."""
    w, h = _frame_size()
    pt = (int(w * fx), int(h * fy))
    click_at(*pt)
    return pt


def open_social(calib_dir: Path) -> tuple[str, tuple[int, int]]:
    """Open the social/friends panel from the home screen. Prefers a calibrated
    'social_icon' template; otherwise clicks the default bottom-bar fraction."""
    scr = grab_screen()
    tp = Path(calib_dir) / "social_icon.png"
    if tp.exists():
        pt = find_template(scr, str(tp))
        if pt is not None:
            click_at(*pt)
            return ("tmpl", pt)
    return ("frac", click_pos_frac(*SOCIAL_ICON_FRAC))


def click_search_button() -> tuple[int, int]:
    """Trigger the add-friend search. Enter does NOT search in this client, so
    we click the magnifier icon (fixed fraction, no text to OCR)."""
    return click_pos_frac(*SEARCH_BTN_FRAC)


def click_search_box() -> tuple[int, int]:
    """Focus the add-friend search box by clicking a fixed fraction. Its grey
    placeholder is too low-contrast for OCR to locate, so text-based focusing
    silently fails (the box never gets focus and the paste goes nowhere)."""
    return click_pos_frac(*SEARCH_BOX_FRAC)


def open_info_popup(calib_dir: Path, timeout: float = 6.0) -> tuple[str, tuple[int, int]]:
    """Click the 信息 button in the player-card popup → opens 角色信息.

    Only the ICON (above the label) is clickable, so we locate the '信息' text
    and click INFO_ICON_DY px above it. We require a near-exact match
    (min_ratio 0.95) so the player name (which contains 信息, e.g. 乱报信息枪毙)
    can never be mistaken for the button. The adjacent 屏蔽 (block) button stays
    well clear horizontally. Falls back to a calibrated open_info.png template."""
    end = time.monotonic() + timeout
    tmpl = Path(calib_dir) / "open_info.png"
    while True:
        _ck()
        scr = grab_screen()
        # crop to the button band + accurate engine: 信息 is too small for the fast
        # engine on the full frame (it reads 屏蔽 but drops 信息).
        tokens = _ocr_region(scr, INFO_POPUP_REGION, CONTROL_OCR_SCALE, fast=False)
        hit = locate_text(tokens, TEXT_CONTROLS["open_info"], scr_shape=scr.shape, min_ratio=0.95)
        if hit is not None:
            x, y = hit[0], hit[1] + int(INFO_ICON_DY * scr.shape[0] / _REF_FRAME_H)
            click_at(x, y)
            return ("ocr-icon", (x, y))
        if tmpl.exists():
            pt = find_template(scr, str(tmpl))
            if pt is not None:
                click_at(*pt)
                return ("tmpl", pt)
        if time.monotonic() >= end:
            break
        time.sleep(0.12 + random.random() * 0.08)
    raise RuntimeError(
        "玩家卡片没弹出来,点不开「信息」。最常见的两个原因:"
        "① 查的是你自己的游戏昵称——游戏不允许从添加好友里打开自己的卡片;"
        "② 对方隐藏了战绩/设置了隐私,头像谁点都没反应。"
        "(都不是的话,确认游戏没被别的窗口挡住、搜索结果里确实有这个人)"
    )


def select_mode(option: str, calib_dir: Path, timeout: float = 6.0) -> tuple[int, int]:
    """Set the 详细数据 mode dropdown to `option` (数据总览 / 排位赛数据).

    The dropdown REMEMBERS the last-used mode across game sessions, so the flow
    must set it explicitly instead of assuming 详细数据 opens on 数据总览 — else
    the 'overview' shot can silently capture ranked data.

    Three things make this reliable:
    1. PRE-CHECK the closed header. If it already shows the wanted mode we return
       immediately — no click. This also dodges a real trap: the opened list does
       NOT repeat the active mode, so trying to "select 数据总览" while already on
       数据总览 would find nothing and falsely fail.
    2. To open, click the header at the position we just OCR'd it (no second
       lookup), then read the option from a band anchored BELOW that header in the
       same column — vs. the old fixed (0.20..0.55) guess the 排位赛数据 option
       could fall outside. The header row is excluded (y strictly below it) so we
       can't just re-toggle it shut.
    3. Both OCR phases are cropped to the dropdown's top area, so they're fast."""
    ranked = "排位" in option
    aliases = ["排位赛数据", "排位赛"] if ranked else ["数据总览"]
    tmpl_name = "dropdown_ranked" if ranked else "dropdown_mode"
    all_modes = ["数据总览", "排位赛数据", "排位赛"]
    head_region = (0.0, 0.05, 1.0, 0.32)   # upper band where the closed header lives

    # 1) find the header (the only mode word visible while the list is closed)
    end = time.monotonic() + timeout
    header = None
    while True:
        _ck()
        scr = grab_screen()
        toks = _ocr_region(scr, head_region, CONTROL_OCR_SCALE)
        header = locate_text(toks, all_modes, region=head_region, scr_shape=scr.shape)
        if header is not None:
            break
        if time.monotonic() >= end:
            raise RuntimeError("没找到数据模式下拉框(「详细数据」页没加载?)")
        time.sleep(0.12 + random.random() * 0.08)

    # already on the wanted mode? done — opening would find nothing to click.
    cur = _norm(header[2].get("text", ""))
    if any(_match_score(_norm(a), cur) >= 0.9 for a in aliases):
        return (header[0], header[1])

    # 2) open the list and pick the option from the band below the header
    hx, hy = header[0], header[1]
    click_at(hx, hy)
    _settle(0.4)
    h, w = scr.shape[:2]          # frame space (the same space hx/hy live in)
    fx, fy = hx / w, hy / h
    # compact band right under the header: same column, ~5 rows tall. The list is
    # short (2-3 modes), so a tall band just OCRs the page body for nothing — the
    # validated option sits ~0.08 below the header, so 0.34 leaves ample margin.
    region = (max(0.0, fx - 0.16), min(0.97, fy + 0.014),
              min(1.0, fx + 0.22), min(0.99, fy + 0.34))
    tmpl_path = Path(calib_dir) / f"{tmpl_name}.png"

    end = time.monotonic() + 5.0
    while True:
        _ck()
        scr = grab_screen()
        toks = _ocr_region(scr, region, CONTROL_OCR_SCALE)
        hit = locate_text(toks, aliases, region=region, scr_shape=scr.shape)
        if hit is not None:
            click_at(hit[0], hit[1])
            return (hit[0], hit[1])
        if tmpl_path.exists():
            pt = find_template(scr, str(tmpl_path))
            if pt is not None:
                click_at(*pt)
                return pt
        if time.monotonic() >= end:
            break
        time.sleep(0.12 + random.random() * 0.08)
    raise RuntimeError(
        f"下拉里没找到「{option}」选项——下拉可能没展开,或选项文字 OCR 不到;"
        f"可在校准页给 {tmpl_name} 拍一张参考图兜底"
    )


def detect_mode(timeout: float = 6.0) -> str:
    """Read which mode (数据总览 / 排位赛数据) the 详细数据 dropdown header is
    showing right now, normalised. The dropdown remembers the last-used mode, so
    the page can open in either — callers snapshot the CURRENT one first and
    switch once, instead of always forcing 总览→排位 (saves a dropdown trip)."""
    head_region = (0.0, 0.05, 1.0, 0.32)
    all_modes = ["数据总览", "排位赛数据", "排位赛"]
    end = time.monotonic() + timeout
    while True:
        _ck()
        scr = grab_screen()
        toks = _ocr_region(scr, head_region, CONTROL_OCR_SCALE)
        hit = locate_text(toks, all_modes, region=head_region, scr_shape=scr.shape)
        if hit is not None:
            return _norm(hit[2].get("text", ""))
        if time.monotonic() >= end:
            raise RuntimeError("没找到数据模式下拉框(「详细数据」页没加载?)")
        time.sleep(0.12 + random.random() * 0.08)


def return_to_lobby(max_steps: int = 6) -> bool:
    """Back out of whatever screens are stacked until the LOBBY HOME (开始游戏
    tab strip) is visible. Returns True when home was confirmed.

    Two live-verified quirks force the verify-each-step design:
    * the number of stacked layers varies (the add-friend dialog may or may not
      still be under the profile), and ONE esc too many overshoots the lobby
      into the mode-select hub — so we check BEFORE each press and stop on home;
    * a STRANGER's profile page (opened via add-friend search, with its mini-card
      overlay) EATS synthetic Esc entirely — but its bottom-left 返回 button is
      clickable, so when esc makes no progress we click 返回 instead. If we ever
      overshoot into the hub anyway, the next esc closes it back to the lobby.
    """
    home_band = (0.0, 0.0, 0.45, 0.16)
    back_band = (0.0, 0.84, 0.65, 1.0)   # 返回 sits bottom-left (profile/social) or bottom-centre (dialogs)
    for _ in range(max_steps):
        _ck()
        scr = grab_screen()              # quick grab (no _wait_stable) — we only
        toks = _ocr_region(scr, home_band, CONTROL_OCR_SCALE)   # need to read text
        if locate_text(toks, ["开始游戏"], region=home_band, scr_shape=scr.shape,
                       min_ratio=0.85) is not None:
            return True
        # Prefer the on-screen 返回 button when it's there (a stranger profile EATS
        # synthetic Esc), else Esc. Checking it every step (not alternating) gets
        # us home in the fewest presses.
        btoks = _ocr_region(scr, back_band, CONTROL_OCR_SCALE)
        hit = locate_text(btoks, ["返回"], region=back_band, scr_shape=scr.shape, min_ratio=0.85)
        if hit is not None:
            click_at(hit[0], hit[1])
        else:
            press("escape")
        time.sleep(0.22)                 # let the layer close before the next read
    return False


# ============================== main sequence ===============================

Progress = Callable[[str, str], None]


def _noop(_a: str, _b: str) -> None:
    pass


def focus_game() -> Optional[str]:
    """Best-effort: bring the 三角洲行动 / Delta Force window to the foreground
    and re-measure its client rect (the coordinate space for grabs and clicks).
    Returns the matched window title, or None (no window / not on Windows)."""
    hit = _find_game_window()
    if hit is None:
        refresh_game_rect()      # clears any stale rect
        return None
    hwnd, title = hit
    # Plain SetForegroundWindow from a background/child process is usually refused
    # by Windows (it just flashes the taskbar). AttachThreadInput to the current
    # foreground thread lifts that lock so the game actually rises to the top of
    # the NORMAL window stack. NOTE: it still can't rise above an *always-on-top*
    # window (e.g. a pinned/topmost app) — those occlude the
    # grab no matter what, which is what the occlusion guard in click_control
    # reports.
    try:
        user32 = ctypes.windll.user32
        cur = ctypes.windll.kernel32.GetCurrentThreadId()
        fg = user32.GetForegroundWindow()
        ft = user32.GetWindowThreadProcessId(fg, 0)
        gt = user32.GetWindowThreadProcessId(hwnd, 0)
        user32.AttachThreadInput(cur, gt, True)
        user32.AttachThreadInput(cur, ft, True)
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.AttachThreadInput(cur, gt, False)
        user32.AttachThreadInput(cur, ft, False)
    except Exception:
        pass
    refresh_game_rect()
    return title


def run_auto_lookup(query: str, calib_dir: Path, save_dir: Path, on_progress: Progress = _noop,
                    lead_seconds: float = 5.0, on_capture: Optional[Callable[[str, str], None]] = None) -> list[Path]:
    """Drive the game to look up `query` and capture the four profile screens.

    Returns the list of saved screenshot paths (order: overview, ranked, recent,
    home) — these can be passed straight to `dfstats.lookup.build_record`.
    The progress callback is called at the start of each STEP with a short
    message; the worker uses it to feed the UI.

    `lead_seconds`: a grace countdown BEFORE any input fires, so the user can
    bring the game to the foreground (the bot also tries to focus it itself).
    Pass 0 to start immediately (e.g. from a test harness that already focused).
    """
    calib_dir = Path(calib_dir)
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    captured: dict[str, Path] = {}

    # Wrap the caller's progress callback so EVERY step boundary is also a cancel
    # checkpoint — a 停止 press takes effect within one step instead of running to
    # the end. (The polling loops below add finer-grained checks inside long waits.)
    _report = on_progress

    def _step(name: str, msg: str) -> None:
        _ck()
        _report(name, msg)

    def shot(name: str) -> None:
        _ck()
        time.sleep(0.08)                 # let any transition begin…
        img = _wait_stable()             # …then wait until the UI stops moving
        p = save_dir / f"{int(time.time())}_{name}.png"
        save_image(img, str(p))
        captured[name] = p
        if on_capture is not None:       # let the caller start OCR right away,
            try:                         # overlapping it with the rest of driving
                on_capture(name, str(p))
            except Exception:
                pass

    def go(name: str, *, region=None, timeout=8.0, required=True):
        _ck()
        return click_control(
            name, calib_dir=calib_dir, candidates=TEXT_CONTROLS.get(name),
            region=region or CONTROL_REGIONS.get(name), timeout=timeout, required=required,
        )

    # Lead-in: act on the GAME, not whatever window was focused when 查询 was
    # clicked. Count down first (mouse stays still, browser/countdown stays
    # visible) so the user can bring 三角洲 to the front, THEN focus the game
    # ourselves as a fallback right before the first click.
    secs = int(round(lead_seconds))
    for i in range(secs, 0, -1):
        _step("lead_in", f"{i} 秒后开始 · 请把《三角洲行动》切到最前面")
        time.sleep(1.0)
    title = focus_game()
    _step("focus", f"激活游戏窗口{('：' + title) if title else '（没找到，按当前窗口继续）'}")
    _settle(0.6)

    # P1 首页 → 社交/好友图标(无文字,固定位置/模板)
    _step("open_social", "打开社交面板")
    open_social(calib_dir)
    _settle(0.5)

    # P2 社交 → 添加好友(文字按钮)
    _step("open_add_friend", "点添加好友")
    go("add_friend_btn", timeout=8)
    # Wait until the dialog is actually OPEN (high-contrast tab text) before
    # touching the box — else we'd click/type on the panel behind it. Non-fatal:
    # if OCR can't confirm it, just settle briefly and push on.
    try:
        # the 好友搜索/申请列表 tabs live in the dialog's left column — crop there
        # (live-measured frac ~(0.22, 0.32)/(0.22, 0.39)) so the poll is fast
        wait_control("friend_dialog", ["好友搜索", "申请列表"], calib_dir=calib_dir,
                     region=(0.12, 0.26, 0.34, 0.46), timeout=6)
    except TimeoutError:
        _settle(0.6)
    _settle(0.2)

    # P3 添加好友 → 搜索框输入 ID
    _step("type_id", f"输入 {query}")
    # The box's grey placeholder is too low-contrast for OCR, so focus it by a
    # FIXED fraction (not text). This is what silently failed before: the OCR box
    # lookup never matched, the box stayed unfocused, and the paste hit nothing.
    click_search_box()
    _settle(0.22)
    type_text(query)
    _settle(0.3)
    # Verify the text actually landed (focus/paste can still miss). The typed
    # query is high-contrast (unlike the placeholder) so OCR can read it back.
    # Crop to just the search-box ROW (y ~0.22-0.40) before OCR — far fewer text
    # boxes than the top half, so the check is ~3x cheaper.
    scr = grab_screen()
    H = scr.shape[0]
    crop = scr[int(0.22 * H):int(0.40 * H), :]
    if locate_text(ocr.ocr_image(crop, fast=True), [query], min_ratio=0.8) is None:
        click_search_box()
        _settle(0.15)
        pyautogui.hotkey("ctrl", "a")     # clear residual, so retry won't double up
        _gauss_pause(0.05, 0.02)
        type_text(query)
        _settle(0.3)

    _step("search", "搜索")
    # this client ignores Enter, so go straight to the reliable trigger (the
    # magnifier icon) — dropping the no-op Enter press saves a keystroke + pause.
    click_search_button()
    _settle(0.5)              # let the result start rendering (the next step polls)

    # P3 → 点搜索结果头像(点头像,不是名字)
    _step("open_result", "点搜索结果")
    click_first_result(query, calib_dir, timeout=8)
    _settle(0.4)

    # P3 弹窗 → 信息(点图标,不是文字标签) → P4 角色信息
    _step("open_info", "进角色信息")
    open_info_popup(calib_dir, timeout=6)
    _settle(0.5)             # popup closes / profile loads (wait_control polls below)
    # profile opened once the "个人信息" tab is on screen (exact match only, so the
    # popup's 信息 button can't masquerade as the 个人信息 tab). Cropped to the tab
    # strip so the poll is fast.
    wait_control("tab_profile", TEXT_CONTROLS["tab_profile"], calib_dir=calib_dir,
                 region=CONTROL_REGIONS["tab_profile"], timeout=8, min_ratio=0.9)

    _step("tab_profile", "截首页")
    # the 信息 button lands DIRECTLY on the 个人信息 tab (live-verified), so the
    # wait above is enough — clicking the tab again would just waste a click.
    shot("home")

    _step("tab_details", "截详细数据")
    go("tab_details")
    _settle(0.35)
    # the dropdown REMEMBERS the last-used mode, so 详细数据 can open in either
    # one — snapshot whatever is showing FIRST, then switch ONCE for the other.
    first_ranked = "排位" in detect_mode()
    shot("ranked" if first_ranked else "overview")
    _step("switch_mode", "切到数据总览" if first_ranked else "切到排位赛数据")
    select_mode("数据总览" if first_ranked else "排位赛数据", calib_dir)
    shot("overview" if first_ranked else "ranked")

    _step("tab_history", "截最近战绩")
    go("tab_history")
    shot("recent")

    _step("return_home", "退回主页")
    return_to_lobby()

    return [captured["overview"], captured["ranked"], captured["recent"], captured["home"]]


# =============================== validation ================================

def check_calibration(calib_dir: Path) -> dict:
    """Report which templates exist (for the UI's calibration page)."""
    calib_dir = Path(calib_dir)
    out = {}
    for name in TEMPLATES:
        p = calib_dir / f"{name}.png"
        out[name] = {"exists": p.exists(), "path": str(p)}
    out["all_ready"] = all(v["exists"] for v in out.values() if isinstance(v, dict))
    return out


if __name__ == "__main__":
    # quick CLI smoke (does NOT touch the game): just take a screenshot
    import sys
    out = Path("data") / "automate_smoke.png"
    save_image(grab_screen(), str(out))
    print(f"screen captured -> {out}, size {pyautogui.size()}")
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        print(check_calibration(Path("data/calibration")))
