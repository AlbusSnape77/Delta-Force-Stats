"""Global desktop notifications for the auto-lookup pipeline.

Two moments matter to the user and BOTH get announced:
* the bot releases the mouse/keyboard (screenshots captured, OCR starting);
* the OCR finishes and the record is in the library (or the run failed/stopped).

Reliability notes (learned the hard way):
* Windows 11 auto-enables Focus Assist (勿扰) while a fullscreen game runs, so
  notification-center toasts are silently suppressed — exactly when we need
  them most. Therefore the primary cue is a TOPMOST auto-closing popup via
  user32.MessageBoxTimeoutW (undocumented but stable since XP): it ignores
  Focus Assist, floats above everything, and dismisses itself.
* We still send a tray balloon (NotifyIcon) so a record lands in the action
  centre, plus a system beep as the instant audio cue.
Everything is best-effort on daemon threads: a notification must never break
or delay the pipeline.
"""
import base64
import ctypes
import subprocess
import threading

_CREATE_NO_WINDOW = 0x08000000

_MB_OK = 0x0
_MB_ICONINFORMATION = 0x40
_MB_SYSTEMMODAL = 0x1000     # keeps the box above fullscreen/topmost windows
_MB_SETFOREGROUND = 0x10000

_BALLOON_PS = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = [System.Drawing.SystemIcons]::Information
$ni.Visible = $true
$ni.BalloonTipTitle = '{title}'
$ni.BalloonTipText = '{msg}'
$ni.ShowBalloonTip(8000)
Start-Sleep -Seconds 9
$ni.Dispose()
"""


def _ps_quote(s: str) -> str:
    return str(s or "").replace("'", "''").replace("\r", " ").replace("\n", " ")


def _balloon(title: str, msg: str) -> None:
    script = _BALLOON_PS.format(title=_ps_quote(title), msg=_ps_quote(msg))
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-EncodedCommand", enc],
        creationflags=_CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _popup(title: str, msg: str, timeout_ms: int = 8000) -> None:
    flags = _MB_OK | _MB_ICONINFORMATION | _MB_SYSTEMMODAL | _MB_SETFOREGROUND
    ctypes.windll.user32.MessageBoxTimeoutW(0, str(msg), str(title), flags, 0, timeout_ms)


def notify(title: str, msg: str, popup: bool = True) -> None:
    """Fire-and-forget: beep + tray balloon (+ topmost auto-closing popup)."""
    def _run():
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass
        try:
            _balloon(title, msg)
        except Exception:
            pass
        if popup:
            try:
                _popup(title, msg)
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True, name="notify").start()
