"""Flask server: upload 4 screenshots -> OCR -> auto-store; plus search/edit/delete.

Run:  python -m dfstats.server   (serves http://localhost:5174 and the LAN address)
"""
import io
import os
import time
from flask import Flask, request, jsonify, send_from_directory, send_file

from . import store, jobs
from .lookup import build_record
from .automate import TEMPLATES, grab_screen, save_image
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
UPLOAD_DIR = os.path.join(ROOT, "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)


def db():
    return store.connect()


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:fname>")
def static_files(fname):
    return send_from_directory(WEB_DIR, fname)


@app.post("/api/lookup")
def lookup():
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "没有收到图片"}), 400

    stamp = time.strftime("%Y%m%d_%H%M%S")
    paths = []
    for i, f in enumerate(files):
        base = os.path.basename(f.filename or f"img{i}.png").replace("\\", "_").replace("/", "_")
        p = os.path.join(UPLOAD_DIR, f"{stamp}_{i}_{base}")
        f.save(p)
        paths.append(p)

    record = build_record(paths)
    nickname = record.get("nickname") or f"未命名_{stamp}"

    conn = db()
    try:
        player = store.upsert_snapshot(conn, nickname, record)
    finally:
        conn.close()

    # OCR finished — drop the screenshots so the uploads folder doesn't grow forever.
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return jsonify({"player": player, "recognized_nickname": record.get("nickname")})


@app.get("/api/players")
def list_players():
    conn = db()
    try:
        return jsonify(store.search(conn, request.args.get("q", "")))
    finally:
        conn.close()


@app.get("/api/players/<int:pid>")
def get_player(pid):
    conn = db()
    try:
        p = store.get_by_id(conn, pid)
        return (jsonify(p), 200) if p else (jsonify({"error": "not found"}), 404)
    finally:
        conn.close()


@app.put("/api/players/<int:pid>")
def put_player(pid):
    body = request.get_json(silent=True) or {}
    conn = db()
    try:
        p = store.update_player(
            conn, pid,
            nickname=body.get("nickname"),
            tags=body.get("tags"),
            note=body.get("note"),
            data=body.get("data"),
        )
        return (jsonify(p), 200) if p else (jsonify({"error": "not found"}), 404)
    finally:
        conn.close()


@app.delete("/api/players/<int:pid>")
def del_player(pid):
    conn = db()
    try:
        ok = store.delete_player(conn, pid)
        return ("", 204) if ok else (jsonify({"error": "not found"}), 404)
    finally:
        conn.close()


# ---- auto-lookup: drive the game client to query a player ID ---------------

@app.post("/api/auto-lookup")
def auto_lookup_submit():
    body = request.get_json(silent=True) or {}
    q = (body.get("query") or "").strip()
    if not q:
        return jsonify({"error": "请输入 ID 或昵称"}), 400
    job_id = jobs.submit_job(q)
    return jsonify({"job_id": job_id})


@app.get("/api/job/<job_id>")
def auto_lookup_job(job_id):
    j = jobs.get_job(job_id)
    if not j:
        return jsonify({"error": "not found"}), 404
    return jsonify(j)


@app.get("/api/jobs")
def auto_lookup_list():
    return jsonify(jobs.list_jobs())


@app.get("/api/auto-stats")
def auto_lookup_stats():
    return jsonify(jobs.stats())


# ---- calibration: capture desktop & save cropped reference templates -------

@app.get("/api/screenshot.png")
def desktop_screenshot():
    img = grab_screen()
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        return jsonify({"error": "encode failed"}), 500
    resp = send_file(io.BytesIO(buf.tobytes()), mimetype="image/png", download_name="screen.png")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.post("/api/calibration/<name>")
def calibration_save(name):
    if name not in TEMPLATES:
        return jsonify({"error": f"unknown template: {name}"}), 400
    f = request.files.get("image")
    if not f:
        return jsonify({"error": "缺少 image 字段"}), 400
    p = jobs.CONFIG["calib_dir"] / f"{name}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(p))
    return jsonify({"ok": True, "name": name, "path": str(p)})


@app.delete("/api/calibration/<name>")
def calibration_delete(name):
    if name not in TEMPLATES:
        return jsonify({"error": "unknown"}), 400
    p = jobs.CONFIG["calib_dir"] / f"{name}.png"
    try:
        p.unlink(missing_ok=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return ("", 204)


def main():
    port = int(os.environ.get("PORT", "5174"))
    print(f"三角洲战绩分析器: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
