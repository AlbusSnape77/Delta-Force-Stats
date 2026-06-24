"""Background single-worker queue for auto-lookup jobs.

One worker is used because the game can only do one query at a time. Jobs go
through pending → running → done/error. A rate-limiter randomises 45–90s
between queries and a per-day cap protects against bot-like burst patterns.
"""
from __future__ import annotations
import datetime
import difflib
import queue
import random
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from . import store
from .automate import (
    check_calibration, run_auto_lookup, LookupCancelled, request_cancel, clear_cancel,
)
from .lookup import build_record
from .notify import notify
from .paths import app_root


CONFIG: dict[str, Any] = {
    "min_interval": 45.0,          # random pause between queries (seconds)
    "max_interval": 90.0,
    "daily_cap": 100,
    "lead_seconds": 3.0,           # grace countdown to bring the game to the front
    # anchored to the app root (NOT the cwd) so the frozen exe and `python -m`
    # both put calibration/screenshots in the same visible place
    "calib_dir": Path(app_root()) / "data" / "calibration",
    "save_dir": Path(app_root()) / "data" / "uploads" / "auto",
}

_jobs: dict[str, dict] = {}
_q: "queue.Queue[str]" = queue.Queue()
_lock = threading.Lock()
_worker_started = False
_last_query_end: float = 0.0
_daily = {"date": "", "n": 0}
# id of the job whose automation is LIVE right now, so cancel_job knows whether to
# signal the in-flight run via automate.request_cancel. None while idle / waiting.
_running_job_id: str | None = None


def _today_iso() -> str:
    return datetime.date.today().isoformat()


def _bump_daily() -> None:
    t = _today_iso()
    if _daily["date"] != t:
        _daily.update(date=t, n=0)
    _daily["n"] += 1


def _under_cap() -> bool:
    if _daily["date"] != _today_iso():
        return True
    return int(_daily["n"]) < int(CONFIG["daily_cap"])


def _set(job_id: str, **kw) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if j:
            j.update(kw)


def submit_job(query: str) -> str:
    job_id = uuid.uuid4().hex[:10]
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "query": query, "state": "pending",
            "step": None, "msg": "排队中",
            "player": None, "error": None, "cancel": False,
            "created_at": time.time(), "started_at": None, "ended_at": None,
        }
    _q.put(job_id)
    _ensure_worker()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def _is_cancelled(job_id: str) -> bool:
    with _lock:
        j = _jobs.get(job_id)
        return bool(j and (j.get("cancel") or j.get("state") == "cancelled"))


def cancel_job(job_id: str) -> dict | None:
    """Request a stop for `job_id`. Returns the updated job, or None if unknown.

    * pending (queued or sleeping in the rate-limiter) → marked 已停止 right away;
      the worker skips it when it reaches it.
    * running → flips the cancel flag; if this job's automation is the one live
      right now we also signal automate.request_cancel so run_auto_lookup bails at
      its next checkpoint (~0.2s) and the worker marks it 已停止.
    Already-finished jobs (done/error/cancelled) are returned unchanged.
    """
    signal = False
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return None
        if j["state"] in ("done", "error", "cancelled"):
            return dict(j)
        j["cancel"] = True
        if job_id == _running_job_id:
            signal = True               # live run → poke the cooperative stop flag
            j["msg"] = "停止中…"
        elif j["state"] == "pending":
            # queued or rate-limited (not yet driving the game) → stop it now
            j.update(state="cancelled", msg="已停止", ended_at=time.time())
        else:
            j["msg"] = "停止中…"
        snap = dict(j)
    if signal:
        request_cancel()
    return snap


def list_jobs(limit: int = 20) -> list[dict]:
    with _lock:
        items = sorted(_jobs.values(), key=lambda j: -j["created_at"])
        return [dict(j) for j in items[:limit]]


def stats() -> dict:
    return {
        "today_count": int(_daily["n"]) if _daily["date"] == _today_iso() else 0,
        "daily_cap": CONFIG["daily_cap"],
        "queue_depth": _q.qsize(),
        "auto_mode": "ocr",          # controls located by on-screen text, no calibration required
        "config": {
            "min_interval": CONFIG["min_interval"],
            "max_interval": CONFIG["max_interval"],
        },
        # kept for the optional calibration page (templates are a fallback only)
        "calibration": check_calibration(CONFIG["calib_dir"]),
    }


def _worker_loop() -> None:
    global _last_query_end, _running_job_id
    while True:
        job_id = _q.get()
        j = get_job(job_id)
        if not j:
            continue

        # stop pressed while the job was still queued
        if _is_cancelled(job_id):
            _set(job_id, state="cancelled", msg="已停止", ended_at=time.time())
            continue

        if not _under_cap():
            _set(job_id, state="error", error="今日查询数已达上限，明天再来", ended_at=time.time())
            continue

        # No calibration gate any more: the bot locates controls by OCR text at
        # run time (calibrated templates are an optional fallback inside automate).
        # If a control truly can't be found, run_auto_lookup raises and the error
        # surfaces on the job below.

        # randomised pause since the last completed query
        wait_target = _last_query_end + random.uniform(CONFIG["min_interval"], CONFIG["max_interval"])
        wait = max(0.0, wait_target - time.time())
        if wait > 0.5:
            _set(job_id, msg=f"限速中，{wait:.0f}s 后开始")
            end = time.time() + wait
            while time.time() < end and not _is_cancelled(job_id):
                time.sleep(min(0.3, max(0.0, end - time.time())))

        # honour a stop that arrived while queued / during the rate-limit wait,
        # before we fire any input at the game
        if _is_cancelled(job_id):
            _set(job_id, state="cancelled", msg="已停止", ended_at=time.time())
            continue

        _set(job_id, state="running", started_at=time.time(), msg="开始")
        with _lock:
            _running_job_id = job_id        # this job now owns the cooperative stop
        clear_cancel()                       # fresh stop flag for this run
        # re-check: a stop racing with the two lines above must still win
        if _is_cancelled(job_id):
            _set(job_id, state="cancelled", msg="已停止", ended_at=time.time())
            with _lock:
                _running_job_id = None
            continue
        try:
            def progress(step: str, msg: str) -> None:
                _set(job_id, step=step, msg=msg)

            # NOTE: OCR is deliberately run AFTER driving, not overlapped with it.
            # Overlapping was measured to be a net LOSS here: the heavy background
            # OCR starves the bot's own OCR-based control location (they fight for
            # CPU), so driving slowed more than the OCR saved.
            paths = run_auto_lookup(
                j["query"], CONFIG["calib_dir"], CONFIG["save_dir"], on_progress=progress,
                lead_seconds=CONFIG["lead_seconds"],
            )

            # first finish-line: the bot just released the mouse/keyboard.
            notify("🖱 鼠标已交还", "截图拿到了，正在本地识别…电脑可以随便用了")

            _set(job_id, step="ocr", msg="本地 OCR 识别中…")
            rec = build_record([str(p) for p in paths])     # 4 frames OCR'd in parallel
            nick = rec.get("nickname") or f"未命名_{int(time.time())}"

            # OCR can confuse look-alike glyphs in the nickname (炤→焰). For a
            # NAME query the game's search already matched the typed text, so
            # when the OCR'd nickname is merely CLOSE to the query, the query
            # (what the user typed) is the truth — prefer it.
            q = (j["query"] or "").strip()
            if q and not q.isdigit() and nick != q:
                if difflib.SequenceMatcher(None, q, nick).ratio() >= 0.6:
                    nick = q
                    rec["nickname"] = q
                    if isinstance(rec.get("home"), dict):
                        rec["home"]["nickname"] = q

            conn = store.connect()
            try:
                player = store.upsert_snapshot(conn, nick, rec)
            finally:
                conn.close()

            # match the manual upload path: drop screenshots once captured
            for p in paths:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

            _set(job_id, state="done", msg="完成", player=player, ended_at=time.time())
            _last_query_end = time.time()
            _bump_daily()
            # the bot has released the mouse/keyboard — tell the user out loud
            notify("✅ 查询完成", f"{nick} 已入库——电脑还给你了，去浏览器看数据吧")

        except LookupCancelled:
            _set(job_id, state="cancelled", msg="已停止", ended_at=time.time())
            notify("⏹ 已停止", "自动查询已中止，电脑还给你了")
        except Exception as e:
            _set(
                job_id, state="error",
                error=str(e) or "未知错误",
                debug=traceback.format_exc(),
                ended_at=time.time(),
            )
            notify("❌ 查询失败", (str(e) or "未知错误")[:80] + "——电脑还给你了")
        finally:
            with _lock:
                _running_job_id = None


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, daemon=True, name="auto-lookup").start()
        _worker_started = True
