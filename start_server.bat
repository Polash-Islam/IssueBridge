@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
python start_server.py
pause