"""Flask server: upload 4 screenshots -> OCR -> auto-store; plus search/edit/delete.

Run:  python -m dfstats.server   (serves http://localhost:5174 and the LAN address)
"""
import os
import time
from flask import Flask, request, jsonify, send_from_directory

from . import store
from .lookup import build_record

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


def main():
    port = int(os.environ.get("PORT", "5174"))
    print(f"三角洲战绩分析器: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
