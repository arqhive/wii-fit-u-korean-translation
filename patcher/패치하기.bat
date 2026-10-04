@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
"%~dp0python\python.exe" "%~dp0patcher\patch.py" %*
echo.
pause
