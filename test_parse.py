"""Validate classify + parse against the real uploaded sample screenshots.

Uses samples/ocr_result.json (OCR output) and the sample images (for W/H).
Run: python test_parse.py   -> prints PASS/FAIL per check, exits 1 on any failure.
"""
import os, json, sys, glob
import cv2

from dfstats.classify import classify
from dfstats import parse

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

with open(os.path.join(SAMPLES, "ocr_result.json"), encoding="utf-8") as f:
    OCR = json.load(f)

# map the 4 uploaded files (sorted) to roles by their classification
files = sorted(OCR.keys())


def dims(fname):
    img = cv2.imread(os.path.join(SAMPLES, fname))
    h, w = img.shape[:2]
    return w, h


fails = []


def check(name, cond, got=None):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + ("" if cond else f"  got={got!r}"))
    if not cond:
        fails.append(name)


# classify all
roles = {classify(OCR[f]): f for f in files}
check("classify overview present", "overview" in roles)
check("classify ranked present", "ranked" in roles)
check("classify recent present", "recent" in roles)
check("classify home present", "home" in roles)

# --- overview ---
if "overview" in roles:
    f = roles["overview"]; W, H = dims(f)
    o = parse.parse_overview(OCR[f], W, H)
    check("overview.matches==853", o["matches"] == 853, o["matches"])
    check("overview.play_hours==175h", o["play_hours"] == "175h", o["play_hours"])
    check("overview.escape_rate==35.3%", o["escape_rate"] == "35.3%", o["escape_rate"])
    check("overview.profit_ratio==1.8M", o["profit_ratio"] == "1.8M", o["profit_ratio"])
    check("overview.rank_star==44", o["rank_star"] == 44, o["rank_star"])
    check("overview.rank_score==8168", o["rank_score"] == 8168, o["rank_score"])
    check("overview.kills==951", o["kills"] == "951", o["kills"])
    check("overview.hit_rate==23.2%", o["hit_rate"] == "23.2%", o["hit_rate"])
    check("overview.precise==52.6%", o["precise_kill_rate"] == "52.6%", o["precise_kill_rate"])
    check("overview.carry_value==987.7M", o["carry_value"] == "987.7M", o["carry_value"])
    r = o["radar"]
    check("overview.radar.战斗==68", r.get("战斗") == 68, r.get("战斗"))
    check("overview.radar.财富==100", r.get("财富") == 100, r.get("财富"))
    check("overview.radar.生存==73", r.get("生存") == 73, r.get("生存"))
    check("overview.radar.搜索==72", r.get("搜索") == 72, r.get("搜索"))
    check("overview.radar.合作==62", r.get("合作") == 62, r.get("合作"))

# --- ranked (toast may cover some sub-fields; check clean core only) ---
if "ranked" in roles:
    f = roles["ranked"]; W, H = dims(f)
    o = parse.parse_overview(OCR[f], W, H)
    check("ranked.matches==492", o["matches"] == 492, o["matches"])
    check("ranked.play_hours==114h", o["play_hours"] == "114h", o["play_hours"])
    check("ranked.escape_rate==30.7%", o["escape_rate"] == "30.7%", o["escape_rate"])
    check("ranked.profit_ratio==2.1M", o["profit_ratio"] == "2.1M", o["profit_ratio"])
    r = o["radar"]
    check("ranked.radar.战斗==73", r.get("战斗") == 73, r.get("战斗"))
    check("ranked.radar.财富==100", r.get("财富") == 100, r.get("财富"))
    check("ranked.radar.搜索==75", r.get("搜索") == 75, r.get("搜索"))

# --- recent ---
if "recent" in roles:
    f = roles["recent"]; W, H = dims(f)
    rec = parse.parse_recent(OCR[f], W, H)
    check("recent.not hidden", rec["hidden"] is False, rec["hidden"])
    check("recent.matches==7", len(rec["matches"]) == 7, len(rec["matches"]))
    if rec["matches"]:
        m0 = rec["matches"][0]
        check("recent[0].result==撤离失败", m0["result"] == "撤离失败", m0["result"])
        check("recent[0].map_time has 22:14", m0["map_time"] and "22:14" in m0["map_time"], m0["map_time"])
        check("recent[0].rank_change has (-18)", m0["rank_change"] and "-18" in m0["rank_change"], m0["rank_change"])

# --- home ---
if "home" in roles:
    f = roles["home"]; W, H = dims(f)
    h = parse.parse_home(OCR[f], W, H)
    check("home.nickname==PeRo追风君子", h["nickname"] == "PeRo追风君子", h["nickname"])
    check("home.total_assets==515.8M", h["total_assets"] == "515.8M", h["total_assets"])
    check("home.total_matches==853", h["total_matches"] == 853, h["total_matches"])
    check("home.almanac==81", h["almanac"] == 81, h["almanac"])

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED: {fails}")
    sys.exit(1)
print("ALL CHECKS PASSED")
