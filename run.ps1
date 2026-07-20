# PrepPilot launcher - always uses the project venv (Python 3.12 + voice stack).
#
# Why this exists: the system Python (3.14, whatever's on PATH) has none of the
# voice packages installed (see CLAUDE.md) - faster-whisper, silero-vad and
# kokoro all silently degrade to no-ops under graceful degradation, so a plain
# `python -m uvicorn backend.main:app` boots fine but transcription quietly
# returns empty text and the interviewer never talks back. Always launch
# through this script (or run.bat) so that mistake isn't possible.
#
# Usage:
#   .\run.ps1            # normal run (Ollama, real voice)
#   .\run.ps1 -Fake       # offline canned-LLM demo mode

param([switch]$Fake)

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: .venv not found at $venvPython" -ForegroundColor Red
    Write-Host ""
    Write-Host "The system Python lacks the voice stack (faster-whisper/silero-vad/kokoro)." -ForegroundColor Yellow
    Write-Host "Transcription would silently return empty text instead of erroring." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Create the project venv first (see CLAUDE.md):"
    Write-Host "  uv venv .venv --python 3.12"
    Write-Host "  uv pip install --python .venv/Scripts/python.exe -r requirements.txt -r requirements-voice.txt"
    Write-Host "  uv pip install --python .venv/Scripts/python.exe nvidia-cudnn-cu12 nvidia-cublas-cu12"
    exit 1
}

if ($Fake) {
    $env:PREPPILOT_LLM__PROVIDER = "fake"
    Write-Host "Launching in FAKE/offline demo mode - all questions and scores are canned." -ForegroundColor Yellow
}

& $venvPython -m uvicorn backend.main:app --port 8000 --ws-ping-interval 25 --ws-ping-timeout 60
