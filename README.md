# PrepPilot — AI-Powered Mock Interview Tutor

Local-first mock interviews with an AI interviewer that **listens to how you speak, not just what you say**. Runs entirely offline on an 8GB laptop GPU (RTX 3070 class); swaps to cloud APIs with one config line.

```
mic → Silero VAD → faster-whisper (word timestamps) → prosody + filler analytics
    → LLM interviewer/coach (Ollama qwen3:8b | Claude Haiku 4.5 | GPT-5 mini)
    → structured rubric feedback → Kokoro TTS asks the next question
```

**Stack:** FastAPI + WebSockets · SQLite/SQLAlchemy · Next.js (static export) · Ollama · faster-whisper · Silero VAD · parselmouth/librosa · Kokoro-82M TTS

**🔗 Links:** [System design](docs/ARCHITECTURE.md) · [Deploy a free demo](DEPLOY.md) · Live demo: `{{DEMO_URL}}` · Demo video: `{{VIDEO_LINK}}`

> A **text-mode** live demo runs on a free CPU host (Render/Koyeb) with canned coaching — no
> GPU, no API key (see [DEPLOY.md](DEPLOY.md)). The **voice** experience (speech-to-text,
> delivery analytics, TTS interviewer) needs a local GPU; run it yourself (below) or watch
> the demo video.

## Features

- **Adaptive interviewer** — one question at a time, targeted follow-ups when an answer is vague or misses a STAR element; calibrated to role, seniority, and a pasted job description.
- **Structured coaching** — 1–10 rubric (content, structure/STAR, specificity, technical accuracy, delivery) with concrete rewrites, referencing your actual words and metrics.
- **Delivery analytics, not black-box emotion labels** — WPM, pause ratio, long pauses, filler rate, pitch variance, energy dynamics, and documented `confidence_proxy` + `expressiveness` composites (formulas in `backend/analytics/metrics.py`). Instant rule-based alerts (pace, fillers, monotone) appear seconds before the LLM feedback, and fillers are highlighted inline in the transcript.
- **Voice or text mode** — full spoken loop (VAD turn-taking, TTS interviewer voice) or type answers with zero heavy dependencies. Launch always via `run.ps1`/`run.bat` so the voice stack can't silently go missing.
- **Question bank** — generate a tailored study list for a role/JD (`/question-bank`), then hand off to a live interview tuned to those categories.
- **Session history dashboard** — per-session reports (printable) with a 1-week practice plan, plus cross-session trend charts for scores and delivery habits and a "filler habits" leaderboard.
- **Provider abstraction** — `config.yaml` switches between local Ollama and Anthropic/OpenAI; automatic fallback if Ollama isn't running (and a canned `fake` provider for offline demos/tests).

## Quickstart (text mode — no GPU needed)

```bash
pip install -r requirements.txt

# Frontend (Next.js static export, served by the backend)
cd frontend && npm install && npm run build && cd ..

# Local LLM (recommended): install Ollama, then
ollama pull qwen3:8b        # ~5.5GB VRAM  (or qwen3:4b, ~2.5GB)

.\run.ps1          # Windows PowerShell — always uses the project .venv
run.bat            # Windows cmd
# open http://127.0.0.1:8000
```

`run.ps1`/`run.bat` always launch through the project venv (`.venv`, Python 3.12)
with the correct WebSocket keepalive flags. **Don't run
`python -m uvicorn backend.main:app` directly** unless you're certain that
Python has every package in `requirements.txt` *and* `requirements-voice.txt`
importable — otherwise voice mode degrades silently (empty transcripts, no
interviewer audio) instead of erroring. See `CLAUDE.md` for the venv setup
these scripts expect.

No Ollama? Set a cloud provider instead:

```bash
# config.yaml → llm.provider: openai   (or anthropic)
export OPENAI_API_KEY=...       # or ANTHROPIC_API_KEY
```

If neither Ollama nor an API key is available, the app still boots with a canned `fake` provider so the UI/flow is demoable.

## Voice mode (Phases 2–3)

```bash
pip install -r requirements-voice.txt   # faster-whisper, silero-vad, kokoro, parselmouth, librosa
```

- Needs CUDA 12 + cuDNN 9 for ctranslate2 (cuDNN 8 → `pip install --force-reinstall ctranslate2==4.4.0`).
- First run downloads Whisper large-v3 (INT8, ~3GB VRAM) and Kokoro (~330MB, runs on CPU).
- Pick **Voice answers** in the setup panel. End-of-turn auto-detects after ~1s of silence ("Done answering" forces it).

### Fitting in 8GB VRAM

Do **not** pin two 7–8B models at once (`OLLAMA_MAX_LOADED_MODELS=1`).

| Strategy | LLM | Whisper | How |
|---|---|---|---|
| **A — co-resident** (lowest latency) | `qwen3:4b` (~2.5GB) | large-v3 INT8 (~3.5GB) pinned | everything stays hot, ~6.5GB total |
| **B — sequential** (best quality, default config) | `qwen3:8b` (~5.5GB) on demand | pinned | Ollama loads/unloads the LLM between turns (~1–2s) |

Optional Ollama env (Windows: user env vars, restart the tray app): `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`.

## Configuration

Everything lives in `config.yaml`; any value can be overridden by env var, e.g. `PREPPILOT_LLM__PROVIDER=anthropic`. Priority: **env > .env > config.yaml > defaults**. Highlights:

- `llm.provider`: `ollama | anthropic | openai` (+ `fallback_provider` when Ollama is down)
- `stt.backend`: `faster-whisper | none` · `tts.backend`: `kokoro | none`
- `analytics.use_ser`: optional wav2vec2 emotion signal (off by default — acted-dataset models are a weak signal; the interpretable prosody metrics are primary)
- `session.max_questions`, `vad.end_of_turn_silence_ms`, etc.

## Development

```bash
.venv/Scripts/python.exe -m pytest tests/ -q   # analytics + VAD unit tests (no GPU required)
cd frontend && npm run dev                      # hot-reload UI on :3000 (proxies to :8000)
.\run.ps1 -Fake                                 # offline backend (canned LLM, run.bat: set PREPPILOT_LLM__PROVIDER=fake & run.bat)
```

## Repo map

```
backend/
  main.py            REST + WebSocket transport, serves frontend/out
  orchestrator.py    async turn state machine (transport/provider agnostic)
  providers/         ollama | anthropic | openai | fake + factory w/ fallback
  prompts/           interviewer, coaching, report, question-bank generation
  audio/             vad (Silero + energy fallback), stt (faster-whisper), tts (Kokoro)
  analytics/         prosody (parselmouth/librosa), fillers, optional SER, metrics
  db/                SQLAlchemy models + repositories (SQLite)
frontend/            Next.js app (TypeScript, App Router, static export, zero CDNs)
modal/deploy.py      Phase-5 stub: serverless GPU STT on Modal (~$1–3/mo, free credit)
tests/               pytest suite (runs without any ML deps)
```

Every heavy dependency is imported lazily and degrades gracefully — the backend boots and the full text loop works with nothing but `requirements.txt` installed.

## What I'd do next

Video/facial-expression track · fine-tuned scoring model · RAG over the candidate's résumé · hosted demo on Modal (stub included).
