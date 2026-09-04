#!/usr/bin/env bash
# SocialAI - start the dashboard (control panel) on http://localhost:8600
cd "$(dirname "$0")"
mkdir -p logs
exec python3 scripts/dashboard.py
