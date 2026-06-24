"""RapidOCR wrapper: full-image OCR plus a helper to re-OCR the KD cell.

The 战损比 (KD) cell shows three values "普通 | 机密 | 绝密" jammed together; full
OCR merges them into one unreliable token. So we crop that cell into three columns
and OCR each separately, which reads each single number reliably.
"""
import re
import cv2
import numpy as np

from .imgio import imread as _imread

_engine = None
_fast_engine = None


def get_engine():
    """The accurate engine for stat parsing (small numbers must stay legible).

    use_angle_cls=False: the angle classifier runs a model over EVERY detected
    box to fix 180°-rotated text — game UI text is never rotated, so it's pure
    waste (measured: ~11s saved across 4 frames sequentially). It only ever
    flips orientation; it never changes how upright text is recognised, so
    turning it off costs zero accuracy here."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR(use_angle_cls=False)
    return _engine


def get_fast_engine():
    """A second engine tuned for LOCATING on-screen UI controls (big labels),
    NOT for parsing stats. Two config changes make it ~2-3x faster with no cost
    to big-text accuracy (measured on the live client frames):

    * det_limit_type='max' (+ a 960 long-side cap): the default 'min' policy
      upscales the SHORT side to 736, which on a 2560x1440 frame (or a cropped
      strip) bloats the detector input. Capping the LONG side shrinks it instead,
      cutting detection from ~1.1s to ~0.3s.
    * use_angle_cls=False: the angle classifier runs per text box to fix rotated
      text — game UI text is never rotated, so it's pure waste (~0.25s/frame).

    The accurate default engine is kept for stats parsing, where small numbers
    must stay legible. (det_model_path=None just lets RapidOCR fill the default
    model path while we override the other Det params.)"""
    global _fast_engine
    if _fast_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _fast_engine = RapidOCR(
            det_model_path=None, use_angle_cls=False,
            det_limit_type="max", det_limit_side_len=960,
        )
    return _fast_engine


def _tokens_from_result(result):
    tokens = []
    for box, text, score in (result or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        tokens.append({
            "text": text,
            "score": round(float(score), 3),
            "x": int(min(xs)), "y": int(min(ys)),
            "x2": int(max(xs)), "y2": int(max(ys)),
        })
    tokens.sort(key=lambda r: (r["y"], r["x"]))
    return tokens


def ocr_image(image, scale=1.0, fast=False):
    """OCR a full image (file path or ndarray) -> list of token dicts.

    `fast=True` uses the control-location engine (see get_fast_engine): ~2-3x
    faster, for finding big on-screen UI labels/buttons. Leave False for stats
    parsing, where small numbers must stay legible.

    `scale` < 1.0 additionally downscales the frame before OCR. Token coordinates
    are always mapped back to the ORIGINAL image space, so callers still click the
    right pixel. With the fast engine the det cap already shrinks the input, so
    scale is usually left at 1.0 there.
    """
    if isinstance(image, str):
        image = _imread(image)
    src = image
    if scale and scale != 1.0:
        src = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    engine = get_fast_engine() if fast else get_engine()
    result, _ = engine(src)
    tokens = _tokens_from_result(result)
    if scale and scale != 1.0 and tokens:
        inv = 1.0 / scale
        for t in tokens:
            t["x"] = int(round(t["x"] * inv)); t["y"] = int(round(t["y"] * inv))
            t["x2"] = int(round(t["x2"] * inv)); t["y2"] = int(round(t["y2"] * inv))
    return tokens


def recognize_box(image, box, pad_y=0.3, pad_x=8):
    """Recognition-only OCR of one crop (no detection pass) -> raw text.
    `image` is a path or ndarray; `box` is (x, y, x2, y2) pixel coords. Used for
    values the detector misses: jammed cells, lone small digits next to icons."""
    if not box:
        return ""
    img = _imread(image) if isinstance(image, str) else image
    if img is None:
        return ""
    x, y, x2, y2 = (int(v) for v in box)
    h = y2 - y
    crop = img[max(0, int(y - h * pad_y)):int(y2 + h * pad_y), max(0, x - pad_x):x2 + pad_x]
    if crop.size == 0:
        return ""
    results, _ = get_engine().text_recognizer([crop])
    return results[0][0] if results else ""


def recognize_boxes(image, boxes, pad_y=0.0, pad_x=0):
    """Recognition-only OCR of MANY crops in ONE batched call -> list of texts
    (aligned to `boxes`, '' for empty crops). The recogniser batches internally,
    so this is far faster than calling recognize_box per box (used for the 8
    per-row kill counts in the history list)."""
    img = _imread(image) if isinstance(image, str) else image
    if img is None:
        return ["" for _ in boxes]
    crops, idx = [], []
    for i, box in enumerate(boxes):
        x, y, x2, y2 = (int(v) for v in box)
        h = y2 - y
        c = img[max(0, int(y - h * pad_y)):int(y2 + h * pad_y), max(0, x - pad_x):x2 + pad_x]
        if c.size:
            crops.append(c); idx.append(i)
    out = ["" for _ in boxes]
    if not crops:
        return out
    results, _ = get_engine().text_recognizer(crops)
    for j, i in enumerate(idx):
        if j < len(results):
            out[i] = results[j][0]
    return out


def ocr_kd(image_path, box):
    """Read the 3 KD values from the 战损比 cell ("1 | 2.2 | 2.2").

    The cell has NO per-value labels in the game UI — just three numbers split
    by thin GRAY vertical bars. Whole-cell recognition reads those bars as extra
    digit '1's ('1|2.2|2.2' -> '11 2.21 2.2' -> garbage like 411.611), so we
    split VISUALLY instead: digits are bright white while the bars are dim, so a
    brightness mask + column projection finds the wide blank gaps between the
    three number groups; each group is then recognised in its own crop.
    Falls back to whole-cell recognition when the split doesn't yield 3 groups.
    Returns up to 3 strings (one per difficulty, '' where unreadable)."""
    if not box:
        return []
    img = _imread(image_path)
    if img is None:
        return []
    x, y, x2, y2 = (int(v) for v in box)
    h = y2 - y
    py0, py1 = max(0, int(y - h * 0.25)), int(y2 + h * 0.25)
    px0, px1 = max(0, x - 6), x2 + 6
    cell = img[py0:py1, px0:px1]
    if cell.size == 0:
        return []

    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
    thr = max(200, int(gray.max()) - 45)        # digits ~white; bars/bg dimmer
    colsum = (gray >= thr).sum(axis=0)
    # digit-group runs of non-empty columns, merging gaps smaller than the
    # intra-number spacing (~0.35*h); the separator gaps are much wider.
    groups = []
    in_run, start = False, 0
    for i, v in enumerate(colsum):
        if v > 0 and not in_run:
            in_run, start = True, i
        elif v == 0 and in_run:
            in_run = False
            groups.append([start, i])
    if in_run:
        groups.append([start, len(colsum)])
    merged = []
    for g in groups:
        if merged and g[0] - merged[-1][1] <= max(6, int(h * 0.35)):
            merged[-1][1] = g[1]
        else:
            merged.append(list(g))

    if len(merged) == 3:
        vals = []
        for gx0, gx1 in merged:
            seg = cell[:, max(0, gx0 - 3):min(cell.shape[1], gx1 + 3)]
            results, _ = get_engine().text_recognizer([seg])
            text = results[0][0] if results else ""
            m = re.search(r"\d+\.\d+|\d+", text)
            vals.append(m.group() if m else "")
        if any(vals):
            return vals

    text = recognize_box(img, (x, y, x2, y2))
    nums = re.findall(r"\d+\.\d+|\d+", text)
    return nums[:3]
