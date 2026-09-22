$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Write-Error "Python 3.11+ est requis."; exit 1 }
Write-Host "Démarrage de Price Monitor sur http://127.0.0.1:8080" -ForegroundColor Cyan
python -m price_monitor.app