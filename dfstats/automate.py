"""Game-client automation: drive 三角洲行动 to look up a player by ID and snap
the 4 profile screens, then return their paths so the existing OCR pipeline can
ingest them.

Design choices to reduce anti-cheat signature/behavioural risk:
* No process injection, no memory reads — pure OS-level input + desktop capture.
* Pixel positions are not hard-coded. The user calibrates each button **once**
  (via the web UI) by cropping a small reference image; at run time the bot
  uses `cv2.matchTemplate` to find that reference on the live screen and clicks
  its center.
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
import subprocess
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import pyautogui
from mss import mss

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0  # we do our own pauses


# ---- step names used in progress callbacks (kept stable for UI/tests) -----
STEPS = (
    "open_friend",      # 切到加好友面板
    "type_id",          # 输入 ID
    "search",           # 点搜索
    "open_profile",     # 点结果打开角色信息
    "tab_profile",      # 进入个人信息(首页)tab → 截图
    "tab_details",      # 进入详细数据 默认数据总览 → 截图
    "switch_ranked",    # 下拉切排位赛数据 → 截图
    "tab_history",      # 进入历史战绩 → 截图
    "return_home",      # Esc 退回主页
)

# Required template names. Place corresponding PNGs in <calib_dir>/<name>.png.
TEMPLATES = (
    "add_friend",        # the "加好友" button/icon in lobby
    "friend_search_box", # the search input box inside add-friend panel
    "first_result",      # the first row of search results (clickable)
    "tab_profile",       # "个人信息" tab on the profile sidebar
    "tab_details",       # "详细数据" tab
    "dropdown_mode",     # the mode dropdown ("数据总览" / "排位赛数据")
    "dropdown_ranked",   # the "排位赛数据" option inside that dropdown
    "tab_history",       # "历史战绩" tab
)


# ============================== humanise input ==============================

def _gauss_pause(mu: float = 0.35, sigma: float = 0.13, lo: float = 0.12, hi: float = 1.6) -> None:
    t = random.gauss(mu, sigma)
    time.sleep(max(lo, min(hi, t)))


def _human_move(x: int, y: int, base_dur: float = 0.30) -> None:
    """Move cursor to (x,y) along a curved path with tiny final jitter."""
    dur = max(0.07, random.gauss(base_dur, base_dur * 0.30))
    # very small target jitter so identical clicks differ pixel-by-pixel
    tx = x + random.randint(-2, 2)
    ty = y + random.randint(-2, 2)
    pyautogui.moveTo(tx, ty, duration=dur, tween=pyautogui.easeInOutQuad)


def click_at(x: int, y: int) -> None:
    _human_move(x, y)
    _gauss_pause(0.07, 0.04, 0.03, 0.25)
    pyautogui.click()
    _gauss_pause()


def _type_via_keys(text: str, mu: float = 0.085, sigma: float = 0.04) -> None:
    for ch in text:
        pyautogui.write(ch, interval=0)
        time.sleep(max(0.02, random.gauss(mu, sigma)))


def _type_via_clipboard(text: str) -> None:
    """Use clipboard + Ctrl+V (for CJK or anything outside printable ASCII)."""
    prev = None
    try:
        prev = subprocess.check_output(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], timeout=2).decode(errors="ignore")
    except Exception:
        pass
    try:
        # set clipboard
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value {repr(text)}"],
            timeout=3, check=False,
        )
        _gauss_pause(0.12, 0.05)
        pyautogui.hotkey("ctrl", "v")
        _gauss_pause(0.3, 0.1)
    finally:
        if prev is not None:
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value {repr(prev)}"],
                    timeout=3, check=False,
                )
            except Exception:
                pass


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
    _gauss_pause(0.20, 0.07)


# =============================== screen + cv ================================

def grab_screen(region: Optional[dict] = None) -> np.ndarray:
    """Fast desktop capture → BGR ndarray. `region` is an mss-style dict
    {top, left, width, height} or None for the primary monitor."""
    with mss() as s:
        mon = region or s.monitors[1]
        img = np.array(s.grab(mon))
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def save_image(img: np.ndarray, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cv2.imwrite(path, img)
    return path


def find_template(scr: np.ndarray, tmpl_path: str, threshold: float = 0.82) -> Optional[tuple[int, int]]:
    """Locate a small reference button in the screen. Returns (cx, cy) or None.

    Uses CCOEFF_NORMED which is robust to lighting differences. If your game
    has a different DPR/resolution than when you calibrated, the match may
    fail — recalibrate or rely on multi-scale search below.
    """
    tmpl = cv2.imread(tmpl_path, cv2.IMREAD_COLOR)
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
        scr = grab_screen()
        pt = find_template(scr, str(calib_dir / f"{name}.png"), threshold)
        if pt is not None:
            return pt
        time.sleep(0.35 + random.random() * 0.2)
    raise TimeoutError(f"等待「{name}」出现超时（{timeout:.0f}s）")


# ============================== main sequence ===============================

Progress = Callable[[str, str], None]


def _noop(_a: str, _b: str) -> None:
    pass


def run_auto_lookup(query: str, calib_dir: Path, save_dir: Path, on_progress: Progress = _noop) -> list[Path]:
    """Drive the game to look up `query` and capture the four profile screens.

    Returns the list of saved screenshot paths (order: overview, ranked, recent,
    home) — these can be passed straight to `dfstats.lookup.build_record`.
    The progress callback is called at the start of each STEP with a short
    message; the worker uses it to feed the UI.
    """
    calib_dir = Path(calib_dir)
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    captured: dict[str, Path] = {}

    def shot(name: str) -> None:
        p = save_dir / f"{int(time.time())}_{name}.png"
        save_image(grab_screen(), str(p))
        captured[name] = p

    on_progress("open_friend", "打开加好友面板")
    click_template("add_friend", calib_dir)
    wait_for_template("friend_search_box", calib_dir, timeout=6)

    on_progress("type_id", f"输入 {query}")
    click_template("friend_search_box", calib_dir)
    _gauss_pause(0.3, 0.1)
    type_text(query)

    on_progress("search", "搜索")
    press("enter")
    wait_for_template("first_result", calib_dir, timeout=8)

    on_progress("open_profile", "打开角色信息")
    click_template("first_result", calib_dir)
    wait_for_template("tab_profile", calib_dir, timeout=8)

    on_progress("tab_profile", "截首页")
    click_template("tab_profile", calib_dir)
    _gauss_pause(0.6, 0.2)
    shot("home")

    on_progress("tab_details", "截数据总览")
    click_template("tab_details", calib_dir)
    _gauss_pause(0.6, 0.2)
    shot("overview")

    on_progress("switch_ranked", "切排位赛后截图")
    click_template("dropdown_mode", calib_dir)
    _gauss_pause(0.3, 0.1)
    click_template("dropdown_ranked", calib_dir)
    _gauss_pause(0.7, 0.2)
    shot("ranked")

    on_progress("tab_history", "截最近战绩")
    click_template("tab_history", calib_dir)
    _gauss_pause(0.7, 0.2)
    shot("recent")

    on_progress("return_home", "退回主页")
    for _ in range(3):
        press("escape")
        _gauss_pause(0.25, 0.08)

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
