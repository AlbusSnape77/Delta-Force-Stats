"""Run RapidOCR on every image in samples/ and write results to UTF-8 JSON.

Avoids console encoding issues by writing to samples/ocr_result.json.
Each image -> list of {text, score, x, y}.
"""
import os, glob, json
from rapidocr_onnxruntime import RapidOCR

engine = RapidOCR()
SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

out = {}
for path in sorted(glob.glob(os.path.join(SAMPLES, "upload_*"))):
    result, _ = engine(path)
    lines = []
    for box, text, score in (result or []):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        lines.append({
            "text": text,
            "score": round(float(score), 2),
            "x": int(min(xs)), "y": int(min(ys)),
            "x2": int(max(xs)), "y2": int(max(ys)),
        })
    lines.sort(key=lambda r: (r["y"], r["x"]))
    out[os.path.basename(path)] = lines

with open(os.path.join(SAMPLES, "ocr_result.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("wrote samples/ocr_result.json")
