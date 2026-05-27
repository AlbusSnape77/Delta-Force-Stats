@echo off
cd /d "%~dp0"

set "PY=python"
if exist "C:\Python314\python.exe" set "PY=C:\Python314\python.exe"

echo ============================================================
echo   Delta Force Stats Analyzer
echo   Browser opens http://localhost:5174 in a few seconds.
echo   If it says cannot connect, wait 2s and press F5 to refresh.
echo   Keep this window open. Close it to stop the program.
echo ============================================================
echo.

start "" /min cmd /c "timeout /t 6 >nul & start http://localhost:5174"
"%PY%" -m dfstats.server

echo.
echo ====== Program stopped. If there is an error above, screenshot this window. ======
pause
