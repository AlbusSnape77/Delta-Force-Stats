"""Orchestrate: a set of uploaded screenshots -> one merged player record.

For each image: OCR -> classify -> parse the matching screen. KD is read via the
dedicated recogniser. Returns a dict with whichever sections were recognised.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from .ocr import ocr_image, ocr_kd, recognize_box, recognize_boxes
from .classify import classify
from . import imgio, parse


def _dims(path):
    img = imgio.imread(path)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    return w, h


def _overview(path, tokens, W, H):
    o = parse.parse_overview(tokens, W, H)
    o["kd"] = ocr_kd(path, o.pop("kd_box", None))
    o.pop("kd_raw", None)
    # values the detector missed under their labels (e.g. 排位赛 赚损比):
    # recognition-only re-crop right below the label
    for key, box in (o.pop("_value_boxes", {}) or {}).items():
        if o.get(key) is None:
            text = recognize_box(path, box, pad_y=0.1)
            m = re.search(r"[-+]?[\d.,]+\s*[%MmKk万亿]?", text or "")
            if m:
                o[key] = m.group().replace(" ", "")
    return o


# The kill count in a history row is a lone small digit beside its icon at a
# fixed column; the full-frame detector misses it, so re-crop each row there
# and run recognition-only. x starts at 0.402 to fully EXCLUDE the skull icon
# (right edge ≈0.4005) — clipped icon pixels otherwise read as a phantom
# leading digit ('2' -> '22'/'82'); the number itself starts at ≈0.404.
_KILLS_X = (0.402, 0.47)


def _recent(path, tokens, W, H):
    rec = parse.parse_recent(tokens, W, H)
    img = imgio.imread(path)
    matches = rec.get("matches", [])
    boxes, owners = [], []
    for m in matches:
        row_y = m.pop("row_y", None)
        m["kills"] = None
        if img is not None and row_y is not None:
            boxes.append((int(_KILLS_X[0] * W), int(row_y - 0.012 * H),
                          int(_KILLS_X[1] * W), int(row_y + 0.034 * H)))
            owners.append(m)
    # recognise ALL kill-count crops in one batched pass (vs one call per row)
    for m, text in zip(owners, recognize_boxes(img, boxes)):
        runs = re.findall(r"\d+", text)
        if runs:
            m["kills"] = int(runs[-1])   # last run: leading icon noise drops off
    return rec


def _process_one(path):
    """OCR + classify + parse ONE screenshot -> (role, data). Self-contained so
    the four screens can run concurrently."""
    W, H = _dims(path)
    if not W:
        return None, None
    tokens = ocr_image(path)
    role = classify(tokens)
    if role in ("overview", "ranked"):
        return role, _overview(path, tokens, W, H)
    if role == "recent":
        return role, _recent(path, tokens, W, H)
    if role == "home":
        return role, parse.parse_home(tokens, W, H)
    return None, None


def parse_named(name, path):
    """Parse a frame whose ROLE IS ALREADY KNOWN (the auto-lookup names each
    screenshot home/overview/ranked/recent), so classification is skipped. Lets
    the caller OCR each shot the moment it's captured, overlapping OCR with the
    bot's remaining driving."""
    W, H = _dims(path)
    if not W:
        return None
    tokens = ocr_image(path)
    if name in ("overview", "ranked"):
        return _overview(path, tokens, W, H)
    if name == "recent":
        return _recent(path, tokens, W, H)
    if name == "home":
        return parse.parse_home(tokens, W, H)
    return None


def build_record(image_paths):
    """Process image paths -> {nickname, overview?, ranked?, recent, home?}.

    The four screens are independent, so they're OCR'd CONCURRENTLY in a thread
    pool: onnxruntime runs inference in C++ and releases the GIL, so this scales
    across cores and cuts the local-OCR wait from ~14s to ~4s on a multi-core box
    (falls back gracefully to roughly sequential on a 1-2 core machine)."""
    record = {}
    paths = list(image_paths)
    if not paths:
        record["recent"] = {"hidden": True, "matches": []}
        record["nickname"] = None
        return record

    with ThreadPoolExecutor(max_workers=min(4, len(paths))) as ex:
        for role, data in ex.map(_process_one, paths):
            if role:
                record[role] = data

    # No recent screen uploaded (or none recognised) => treat as hidden stats.
    if "recent" not in record:
        record["recent"] = {"hidden": True, "matches": []}

    record["nickname"] = (record.get("home") or {}).get("nickname")
    return record
