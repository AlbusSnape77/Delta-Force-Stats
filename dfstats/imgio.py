"""Unicode-safe image file IO.

cv2.imread/imwrite use the C runtime's narrow-char fopen on Windows and FAIL
SILENTLY on paths containing non-ASCII characters (e.g. the packaged exe living
in a 三角洲战绩分析器/ folder, or a Chinese user-name desktop). Routing the bytes
through numpy's fromfile/tofile keeps the filesystem access in Python (which
handles unicode paths fine) and only hands cv2 in-memory buffers.
"""
import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def imwrite(path, img, ext=None):
    path = str(path)
    if ext is None:
        dot = path.rfind(".")
        ext = path[dot:] if dot != -1 else ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(path)
    return True
