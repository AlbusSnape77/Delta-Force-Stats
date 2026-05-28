"""Background single-worker queue for auto-lookup jobs.

One worker is used because the game can only do one query at a time. Jobs go
through pending → running → done/error. A rate-limiter randomises 45–90s
between queries and a per-day cap protects against bot-like burst patterns.
"""
from __future__ import annotations
import datetime
import queue
import random
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from . import store
from .automate import check_calibration, run_auto_lookup
from .lookup import build_record


CONFIG: dict[str, Any] = {
    "min_interval": 45.0,          # random pause between queries (seconds)
    "max_interval": 90.0,
    "daily_cap": 100,
    "calib_dir": Path("data/calibration"),
    "save_dir": Path("data/uploads/auto"),
}

_jobs: dict[str, dict] = {}
_q: "queue.Queue[str]" = queue.Queue()
_lock = threading.Lock()
_worker_started = False
_last_query_end: float = 0.0
_daily = {"date": "", "n": 0}


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
            "player": None, "error": None,
            "created_at": time.time(), "started_at": None, "ended_at": None,
        }
    _q.put(job_id)
    _ensure_worker()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def list_jobs(limit: int = 20) -> list[dict]:
    with _lock:
        items = sorted(_jobs.values(), key=lambda j: -j["created_at"])
        return [dict(j) for j in items[:limit]]


def stats() -> dict:
    return {
        "today_count": int(_daily["n"]) if _daily["date"] == _today_iso() else 0,
        "daily_cap": CONFIG["daily_cap"],
        "queue_depth": _q.qsize(),
        "config": {
            "min_interval": CONFIG["min_interval"],
            "max_interval": CONFIG["max_interval"],
        },
        "calibration": check_calibration(CONFIG["calib_dir"]),
    }


def _worker_loop() -> None:
    global _last_query_end
    while True:
        job_id = _q.get()
        j = get_job(job_id)
        if not j:
            continue

        if not _under_cap():
            _set(job_id, state="error", error="今日查询数已达上限，明天再来", ended_at=time.time())
            continue

        cal = check_calibration(CONFIG["calib_dir"])
        if not cal.get("all_ready"):
            missing = [k for k, v in cal.items() if isinstance(v, dict) and not v["exists"]]
            _set(job_id, state="error", error=f"还没校准这些按钮：{', '.join(missing)}", ended_at=time.time())
            continue

        # randomised pause since the last completed query
        wait_target = _last_query_end + random.uniform(CONFIG["min_interval"], CONFIG["max_interval"])
        wait = max(0.0, wait_target - time.time())
        if wait > 0.5:
            _set(job_id, msg=f"限速中，{wait:.0f}s 后开始")
            time.sleep(wait)

        _set(job_id, state="running", started_at=time.time(), msg="开始")
        try:
            def progress(step: str, msg: str) -> None:
                _set(job_id, step=step, msg=msg)

            paths = run_auto_lookup(
                j["query"], CONFIG["calib_dir"], CONFIG["save_dir"], on_progress=progress
            )

            _set(job_id, step="ocr", msg="本地 OCR 识别中…")
            rec = build_record([str(p) for p in paths])
            nick = rec.get("nickname") or f"未命名_{int(time.time())}"

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

        except Exception as e:
            _set(
                job_id, state="error",
                error=str(e) or "未知错误",
                debug=traceback.format_exc(),
                ended_at=time.time(),
            )


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, daemon=True, name="auto-lookup").start()
        _worker_started = True
