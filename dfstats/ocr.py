"""RapidOCR wrapper: full-image OCR plus a helper to re-OCR the KD cell.

The 战损比 (KD) cell shows three values "普通 | 机密 | 绝密" jammed together; full
OCR merges them into one unreliable token. So we crop that cell into three columns
and OCR each separately, which reads each single number reliably.
"""
import re
import cv2
import numpy as np

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


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


def ocr_image(image):
    """OCR a full image (file path or ndarray) -> list of token dicts."""
    result, _ = get_engine()(image)
    return _tokens_from_result(result)


def ocr_kd(image_path, box):
    """Read the 3 KD values (普通/机密/绝密) from the 战损比 cell.

    Detection fails on this jammed cell, so we recognise the whole cell directly
    (recognition-only). The recogniser keeps the separators (e.g. '7.2I 1.2I 1.9',
    '0|1.3| 2'), so we just extract the numeric tokens. Returns up to 3 strings.
    """
    if not box:
        return []
    img = cv2.imread(image_path)
    if img is None:
        return []
    x, y, x2, y2 = box
    h = y2 - y
    crop = img[max(0, int(y - h * 0.3)):int(y2 + h * 0.3), max(0, x - 8):x2 + 8]
    if crop.size == 0:
        return []
    results, _ = get_engine().text_recognizer([crop])
    text = results[0][0] if results else ""
    nums = re.findall(r"\d+\.\d+|\d+", text)
    return nums[:3]
