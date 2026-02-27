$VENV_DIR = ".venv"
$PYTHON = "python"
$STAMP = "$VENV_DIR\.requirements_stamp"

if (-not (Test-Path "$VENV_DIR")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    & $PYTHON -m venv $VENV_DIR
}

& "$VENV_DIR\Scripts\Activate.ps1"

if (-not (Test-Path $STAMP) -or ((Get-Item "requirements.txt").LastWriteTime -gt (Get-Item $STAMP).LastWriteTime)) {
    Write-Host "Requirements changed - installing..." -ForegroundColor Cyan
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv pip install -r requirements.txt
    } else {
        pip install -r requirements.txt
    }
    New-Item -ItemType File -Force -Path $STAMP | Out-Null
} else {
    Write-Host "Requirements up to date - skipping install." -ForegroundColor Green
}

Write-Host "Starting backend on http://localhost:8082 ..." -ForegroundColor Green
uvicorn app:app --host 0.0.0.0 --port 8082 --reload
