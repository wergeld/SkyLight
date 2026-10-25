$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "StarLight: http://localhost:8501"
Write-Host "Press Ctrl+C to stop. Data persists in the starlight_data Docker volume."

docker compose up --build
