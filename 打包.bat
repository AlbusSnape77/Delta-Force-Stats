@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python build_exe.py %1
) else (
  C:\Python314\python.exe build_exe.py %1
)
pause
