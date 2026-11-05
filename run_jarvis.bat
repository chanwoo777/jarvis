@echo off
rem Double-click to start Jarvis. Add --text to type instead of talking.
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py %*
rem Keep the window open only if something went wrong, so the error can be read.
if errorlevel 1 pause
