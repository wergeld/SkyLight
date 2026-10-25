#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "StarLight: http://localhost:8501"
echo "Press Ctrl+C to stop. Data persists in the starlight_data Docker volume."
exec docker compose up --build
