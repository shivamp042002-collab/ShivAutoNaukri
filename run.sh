#!/usr/bin/env bash
# One-command runner for macOS / Linux. Creates a virtual env on first use.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || { echo "[!] Copy .env.example to .env and add GEMINI_API_KEY"; exit 1; }
[ -f profile.json ] || { echo "[!] Copy profile.example.json to profile.json and fill it in"; exit 1; }
exec .venv/bin/python main.py "$@"
