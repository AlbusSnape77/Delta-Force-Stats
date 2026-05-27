"""Orchestrate: a set of uploaded screenshots -> one merged player record.

For each image: OCR -> classify -> parse the matching screen. KD is read via the
dedicated recogniser. Returns a dict with whichever sections were recognised.
"""
import cv2

from .ocr import ocr_image, ocr_kd
from .classify import classify
from . import parse


def _dims(path):
    img = cv2.imread(path)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    return w, h


def _overview(path, tokens, W, H):
    o = parse.parse_overview(tokens, W, H)
    o["kd"] = ocr_kd(path, o.pop("kd_box", None))
    o.pop("kd_raw", None)
    return o


def build_record(image_paths):
    """Process image paths -> {nickname, overview?, ranked?, recent, home?}."""
    record = {}
    for path in image_paths:
        W, H = _dims(path)
        if not W:
            continue
        tokens = ocr_image(path)
        role = classify(tokens)
        if role == "overview":
            record["overview"] = _overview(path, tokens, W, H)
        elif role == "ranked":
            record["ranked"] = _overview(path, tokens, W, H)
        elif role == "recent":
            record["recent"] = parse.parse_recent(tokens, W, H)
        elif role == "home":
            record["home"] = parse.parse_home(tokens, W, H)

    # No recent screen uploaded (or none recognised) => treat as hidden stats.
    if "recent" not in record:
        record["recent"] = {"hidden": True, "matches": []}

    record["nickname"] = (record.get("home") or {}).get("nickname")
    return record
