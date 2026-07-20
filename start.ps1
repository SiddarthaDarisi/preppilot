# start.ps1 - launch EVERYTHING for a full voice session:
#   Ollama (LLM) + PrepPilot server (voice .venv) + browser.
# Run from the project root:  .\start.ps1
#
# This is the "just make voice work" entry point. It:
#   1. frees port 8000 (kills a stale/wrong-Python server if one is holding it)
#   2. starts Ollama if it isn't already running
#   3. opens the browser once the server is up
#   4. runs the server in THIS window (Ctrl+C to stop everything)

$root = $PSScriptRoot
$venv = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venv)) {
    Write-Host "ERROR: .venv not found at $venv" -ForegroundColor Red
    Write-Host "The voice stack lives in the project venv. Create it first (see CLAUDE.md):"
    Write-Host "  uv venv .venv --python 3.12"
    Write-Host "  uv pip install --python .venv/Scripts/python.exe -r requirements.txt -r requirements-voice.txt"
    Write-Host "  uv pip install --python .venv/Scripts/python.exe nvidia-cudnn-cu12 nvidia-cublas-cu12"
    exit 1
}

# 1. Free port 8000 (a wrong-Python 'python -m uvicorn' server would block voice).
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

# 2. Start Ollama if it isn't already listening (needed for real, non-demo coaching).
if (-not (Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)) {
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        Write-Host "Starting Ollama..." -ForegroundColor Cyan
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    } else {
        Write-Host "WARNING: Ollama not found on PATH - the app will run in DEMO mode (canned answers)." -ForegroundColor Yellow
        Write-Host "         Install Ollama and 'ollama pull qwen3:8b' for real coaching." -ForegroundColor Yellow
    }
}

# 3. Open the browser once the server has had a moment to boot.
Start-Job { Start-Sleep 8; Start-Process "http://127.0.0.1:8000/" } | Out-Null

# 4. Run the server in this window (voice .venv + WebSocket keepalive flags).
Write-Host "Starting PrepPilot on http://127.0.0.1:8000  (Ctrl+C to stop)" -ForegroundColor Green
& $venv -m uvicorn backend.main:app --port 8000 --ws-ping-interval 25 --ws-ping-timeout 60
