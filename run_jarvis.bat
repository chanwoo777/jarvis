@echo off
rem Double-click to start Jarvis. Add --text to type instead of talking.
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py %*
pause
