@echo off
rem Double-click to check that Jarvis can hear you. Press Ctrl+C or close the window to stop.
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py --mic-test
pause
