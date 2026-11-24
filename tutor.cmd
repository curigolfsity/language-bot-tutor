@echo off
rem Control the background tutor (API + Telegram bot). Try: tutor status
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\tutor.py" %*
