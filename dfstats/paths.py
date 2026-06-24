"""One source of truth for where the app keeps its files.

Normally that's the project root (the directory holding dfstats/ and web/).
Inside a PyInstaller exe, ``__file__`` points into the bundle's _internal/
directory — data written there would be hidden next to the DLLs — so when
frozen we anchor everything to the EXE's directory instead: data/ and web/
sit visibly beside the exe, easy to back up or edit.
"""
import os
import sys


def app_root() -> str:
    if getattr(sys, "frozen", False):          # running as a PyInstaller bundle
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_root() -> str:
    """Read-only bundled resources (PyInstaller _internal dir) when frozen,
    else the project root. Used to FALL BACK for resources shipped inside the
    bundle (e.g. web/) when no copy exists next to the exe."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_root())
    return app_root()
