@echo off
REM PrepPilot launcher - always uses the project venv (Python 3.12 + voice stack).
REM
REM Why this exists: the system Python has none of the voice packages installed
REM (see CLAUDE.md) - faster-whisper, silero-vad and kokoro all silently
REM degrade to no-ops under graceful degradation, so a plain
REM "python -m uvicorn backend.main:app" boots fine but transcription quietly
REM returns empty text and the interviewer never talks back. Always launch
REM through this script (or run.ps1) so that mistake isn't possible.
REM
REM Usage:
REM   run.bat                                       run normally (Ollama, real voice)
REM   set PREPPILOT_LLM__PROVIDER=fake ^& run.bat    offline canned-LLM demo mode

set VENV_PYTHON=%~dp0.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo ERROR: .venv not found at %VENV_PYTHON%
    echo.
    echo The system Python lacks the voice stack ^(faster-whisper/silero-vad/kokoro^).
    echo Transcription would silently return empty text instead of erroring.
    echo.
    echo Create the project venv first ^(see CLAUDE.md^):
    echo   uv venv .venv --python 3.12
    echo   uv pip install --python .venv/Scripts/python.exe -r requirements.txt -r requirements-voice.txt
    echo   uv pip install --python .venv/Scripts/python.exe nvidia-cudnn-cu12 nvidia-cublas-cu12
    exit /b 1
)

if defined PREPPILOT_LLM__PROVIDER (
    if "%PREPPILOT_LLM__PROVIDER%"=="fake" (
        echo Launching in FAKE/offline demo mode - all questions and scores are canned.
    )
)

"%VENV_PYTHON%" -m uvicorn backend.main:app --port 8000 --ws-ping-interval 25 --ws-ping-timeout 60
