# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller --noconfirm dfstats_app.spec      (or use 打包.bat / build_exe.py)
# Output: dist/<APP_NAME>/<APP_NAME>.exe  (one-dir; data/ appears beside the exe on first run)
# APP_NAME defaults to 三角洲战绩分析器; build_exe.py overrides it via the
# DF_APP_NAME env var to stamp a version into the folder/exe name.
import os

from PyInstaller.utils.hooks import collect_data_files

APP_NAME = os.environ.get("DF_APP_NAME", "三角洲战绩分析器")

datas = []
# rapidocr_onnxruntime loads its det/cls/rec submodules DYNAMICALLY:
# rapid_ocr_api.py appends its own package dir to sys.path and imports them by
# bare name ('ch_ppocr_v3_det'), so the whole package must exist ON DISK inside
# the bundle — .py files included — plus config.yaml and the .onnx models.
datas += collect_data_files("rapidocr_onnxruntime", include_py_files=True)
# the web frontend, served from the bundle when no web/ sits beside the exe
datas += [("web", "web")]

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # imported by rapidocr's dynamically-loaded submodules — invisible to
        # PyInstaller's static analysis, so they must be forced in here
        "onnxruntime",
        "pyclipper",
        "yaml",
        "six",
        "shapely",
        "shapely.geometry",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,           # keep the console: server log + closing it quits
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
