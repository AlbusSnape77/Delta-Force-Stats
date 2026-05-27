"""Classify a screenshot into one of the 4 known Delta Force screens.

Input: list of OCR tokens (dicts with at least a "text" key).
Output: one of 'overview' | 'ranked' | 'recent' | 'home' | 'unknown'.

Classification relies on distinctive text markers, not pixel positions, so it is
robust to resolution differences.
"""


def _texts(tokens):
    return [t.get("text", "") for t in tokens]


def classify(tokens):
    texts = _texts(tokens)
    joined = "".join(texts)

    # The 数据总览 / 排位赛 screens are told apart by their dropdown label.
    if any("排位赛" in t for t in texts):
        return "ranked"
    if any("数据总览" in t for t in texts):
        return "overview"

    # 最近战绩: several 撤离成功/撤离失败 rows and no overview/ranked dropdown.
    escape_rows = sum(1 for t in texts if ("撤离成功" in t or "撤离失败" in t))
    if escape_rows >= 2:
        return "recent"

    # 首页: 当前赛季 + 收藏室/成就徽章 panels.
    if "当前赛季" in joined or ("收藏室" in joined and "成就徽章" in joined):
        return "home"

    return "unknown"
