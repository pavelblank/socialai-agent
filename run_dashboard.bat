@echo off
rem SocialAI - start the dashboard (control panel) on http://localhost:8600
cd /d "%~dp0"
if not exist logs mkdir logs
python scripts\dashboard.py
