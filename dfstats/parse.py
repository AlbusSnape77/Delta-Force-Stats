"""Parse OCR tokens from Delta Force screens into structured fields.

Tokens are dicts: {"text", "x", "y", "x2", "y2", "score"}.
Extraction uses label-anchoring (find a label token, then the value directly
below it or to its right on the same row), with tolerances relative to image
size so it generalises across resolutions.
"""
import re

# ---- token geometry helpers ------------------------------------------------


def cx(t):
    return (t["x"] + t["x2"]) / 2


def cy(t):
    return (t["y"] + t["y2"]) / 2


def find_label(tokens, name, exact=False):
    """First token whose text equals (exact) or contains (default) `name`."""
    for t in tokens:
        txt = t.get("text", "")
        if (txt == name) if exact else (name in txt):
            return t
    return None


def value_below(tokens, label, W, H):
    """Nearest token centred roughly under `label` and below it."""
    if not label:
        return None
    x_tol = 0.05 * W
    y_max = 0.07 * H
    best, best_dy = None, None
    for t in tokens:
        if t is label:
            continue
        dy = cy(t) - cy(label)
        if dy <= 0 or dy > y_max:
            continue
        if abs(cx(t) - cx(label)) > x_tol:
            continue
        if best is None or dy < best_dy:
            best, best_dy = t, dy
    return best


def value_right(tokens, label, W, H, numeric=False):
    """Nearest token to the right of `label` on the same row.
    If numeric=True, only number-like tokens are considered (so a missing value
    does not accidentally pick up the next label)."""
    if not label:
        return None
    y_tol = 0.02 * H
    best, best_dx = None, None
    for t in tokens:
        if t is label:
            continue
        if abs(cy(t) - cy(label)) > y_tol:
            continue
        dx = t["x"] - label["x2"]
        if dx <= -5:
            continue
        if numeric and not is_number_token(t["text"]):
            continue
        if best is None or dx < best_dx:
            best, best_dx = t, dx
    return best


def txt(tok):
    return tok["text"].strip() if tok else None


# ---- value normalisers -----------------------------------------------------

_INT_RE = re.compile(r"^\s*[★\s]*(\d+)\s*$")
_NUM_TOKEN_RE = re.compile(r"^[\d.,]+[%MmKkBbHh]?$")


def as_int(s):
    if not s:
        return None
    m = re.search(r"-?\d+", s.replace(",", ""))
    return int(m.group()) if m else None


def is_number_token(s):
    s = s.strip()
    return bool(_NUM_TOKEN_RE.match(s)) or s.startswith("★")


# ---- radar (五维) ----------------------------------------------------------


def parse_radar(tokens, W, H):
    """Return {战斗,生存,合作,搜索,财富} ints. 战斗 has no text label (top vertex),
    so it is taken as the top-most numeric value in the radar region."""
    x_min, y_min, y_max = 0.72 * W, 0.27 * H, 0.55 * H
    vals = [
        t for t in tokens
        if cx(t) > x_min and y_min < cy(t) < y_max and as_int(t["text"]) is not None
        and len(re.sub(r"\D", "", t["text"])) <= 3
    ]
    if not vals:
        return {}
    labels = {n: find_label(tokens, n, exact=True) for n in ("财富", "生存", "搜索", "合作")}
    labels = {n: l for n, l in labels.items() if l and cx(l) > x_min}

    radar = {}
    vals_sorted = sorted(vals, key=cy)
    top = vals_sorted[0]
    radar["战斗"] = as_int(top["text"])
    rest = vals_sorted[1:]

    used = set()
    for name, lab in labels.items():
        best, best_d = None, None
        for i, v in enumerate(rest):
            if i in used:
                continue
            d = (cx(v) - cx(lab)) ** 2 + (cy(v) - cy(lab)) ** 2
            if best is None or d < best_d:
                best, best_d, best_i = v, d, i
        if best is not None:
            radar[name] = as_int(best["text"])
            used.add(best_i)
    return radar


# ---- overview / ranked -----------------------------------------------------


def parse_overview(tokens, W, H):
    """Parse 数据总览 or 排位赛 (identical layout). Returns a dict of fields.
    KD (战损比) is returned raw plus its bounding box for re-crop OCR."""
    out = {}

    season = find_label(tokens, "S9", exact=False)
    out["season"] = txt(season)

    rank_name = find_label(tokens, "三角洲", exact=False)
    out["rank_name"] = txt(rank_name)
    if rank_name:
        out["rank_star"] = as_int(txt(value_right(tokens, rank_name, W, H)))
        out["rank_score"] = as_int(txt(value_below(tokens, rank_name, W, H)))

    out["matches"] = as_int(txt(value_below(tokens, find_label(tokens, "战局数"), W, H)))
    out["play_hours"] = txt(value_below(tokens, find_label(tokens, "游戏时长"), W, H))

    out["radar"] = parse_radar(tokens, W, H)

    out["profit_ratio"] = txt(value_below(tokens, find_label(tokens, "赚损比"), W, H))
    out["escape_rate"] = txt(value_below(tokens, find_label(tokens, "撤离率"), W, H))

    kd_label = find_label(tokens, "战损比")
    kd_val = value_below(tokens, kd_label, W, H)
    out["kd_raw"] = txt(kd_val)
    out["kd_box"] = [kd_val["x"], kd_val["y"], kd_val["x2"], kd_val["y2"]] if kd_val else None

    # sub-rows (label -> value to the right)
    pairs = {
        "carry_value": "带出价值",
        "action_reward": "累计行动报酬",
        "mandel_bricks": "累计破译曼德尔砖",
        "kills": "击败干员",
        "hit_rate": "命中率",
        "precise_kill_rate": "精准击败率",
        "carry_teammate_value": "带出队友价值",
        "rescue_teammate": "救助队友",
        "revive_teammate": "复活队友",
    }
    for key, label in pairs.items():
        out[key] = txt(value_right(tokens, find_label(tokens, label), W, H, numeric=True))
    return out


def split_kd(values_text):
    """Best-effort split of a merged KD string like '7.21.21.9' -> [7.2,1.2,1.9].
    NOTE: unreliable; the server should prefer re-cropping the KD box. Used as fallback."""
    if not values_text:
        return []
    nums = re.findall(r"\d+\.\d|\d+", values_text)
    return nums


# ---- recent matches --------------------------------------------------------


def parse_recent(tokens, W, H):
    """Return {hidden: bool, matches: [...]} from the 最近/历史战绩 list."""
    # a match "row" is a 2-line block (result on top, map+time below), so the
    # band must be wide enough to include the line below but not the next match.
    y_tol = 0.05 * H
    anchors = [t for t in tokens if ("撤离成功" in t["text"] or "撤离失败" in t["text"])]
    matches = []
    for a in anchors:
        row = [t for t in tokens if abs(cy(t) - cy(a)) < y_tol and t is not a]
        info = {"result": "撤离成功" if "撤离成功" in a["text"] else "撤离失败"}
        # map + time (left, contains a date/time)
        mt = next((t for t in row if re.search(r"\d{1,2}:\d{2}", t["text"])), None)
        info["map_time"] = txt(mt)
        # 哈夫币: the large comma number near the middle
        hafu = next((t for t in row if re.match(r"^[\d.,]{4,}$", t["text"]) and 0.35 * W < cx(t) < 0.6 * W), None)
        info["hafu"] = txt(hafu)
        # rank change: right side token containing parentheses like 8130(-18)
        rc = next((t for t in row if "(" in t["text"] or ")" in t["text"]), None)
        info["rank_change"] = txt(rc)
        matches.append(info)
    return {"hidden": len(matches) == 0, "matches": matches}


# ---- home ------------------------------------------------------------------


def parse_home(tokens, W, H):
    """Parse 首页: nickname, title, season summary numbers, collection/almanac."""
    out = {}
    known_labels = {
        "角色信息", "烽火地带", "全面战场", "个人信息", "历史战绩", "详细数据",
        "账号成就", "社交定制", "信誉档案", "当前赛季", "赛季最高", "收藏室",
        "成就徽章", "总战局", "总资产", "游戏时长", "撤离率", "击败干员",
        "赚损比", "高校特权", "游戏中心启动", "三角洲巅峰", "图鉴收集",
    }

    # nickname: a CJK text token in the right region, not a known label / number / watermark
    cands = []
    for t in tokens:
        s = t["text"].strip()
        if cx(t) < 0.6 * W or cy(t) < 0.5 * H:
            continue
        if not re.search(r"[一-鿿 A-Za-z]", s):
            continue
        if s in known_labels or s.startswith("CN") or is_number_token(s) or "ms" in s:
            continue
        if "大师" in s or "猛攻" in s:  # title line, skip as nickname
            continue
        cands.append(t)
    cands.sort(key=cy)
    out["nickname"] = txt(cands[0]) if cands else None

    title = find_label(tokens, "大师")
    out["title"] = txt(title)
    out["likes"] = as_int(txt(find_label(tokens, "图鉴收集")))  # placeholder; refined below

    out["total_assets"] = txt(value_below(tokens, find_label(tokens, "总资产"), W, H))
    out["total_matches"] = as_int(txt(value_below(tokens, find_label(tokens, "总战局"), W, H)))
    almanac = find_label(tokens, "图鉴收集")
    out["almanac"] = as_int(txt(almanac))
    return out
