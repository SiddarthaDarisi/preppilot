# PrepPilot — project context for Claude Code

AI-powered mock interview tutor. Local-first: runs fully offline on an RTX 3070 laptop (8GB VRAM), swappable to cloud LLM APIs via config. Built and smoke-tested; Phases 1–4 of the spec are complete (text loop, voice loop, delivery analytics, history dashboard). Phase 5 (hosted Modal demo) is a stub in `modal/deploy.py`.

## Architecture

```
Browser (Next.js static export, served by FastAPI)
  ⇅ WebSocket /ws/session/{id}  (binary = 16kHz mono PCM16 mic frames; JSON = control/results)
FastAPI (backend/main.py)
  → Silero VAD turn detection      backend/audio/vad.py     (energy fallback)
  → faster-whisper large-v3 STT    backend/audio/stt.py     (word timestamps required)
  → delivery analytics             backend/analytics/       (parselmouth+librosa prosody,
                                    filler regex, optional wav2vec2 SER, confidence_proxy)
  → LLM interviewer/coach          backend/providers/       (ollama | anthropic | openai | fake)
  → Kokoro TTS interviewer voice   backend/audio/tts.py     (CPU)
  → SQLite persistence             backend/db/              (SQLAlchemy 2.0)
```

- `backend/orchestrator.py` — async turn state machine, transport- and provider-agnostic. The WS layer in `main.py` and the REST endpoints both drive it.
- `backend/schemas.py` — THE shared contract (Pydantic models + WS protocol documented at bottom). Change here ripples everywhere; frontend TS mirrors live in `frontend/src/lib/types.ts`.
- `backend/prompts/` — interviewer, coaching (1–10 rubric + STAR), report, question-bank generation. All LLM output is strict JSON parsed via `complete_json()` (strips ```fences and <think> blocks, retries once on validation failure).
- `backend/config.py` — settings priority: env (`PREPPILOT_*`, `__` nesting) > .env > `config.yaml` > defaults. Keep it that way (uses `settings_customise_sources`).

## Hard rules

- **Graceful degradation is non-negotiable.** Heavy deps (faster-whisper, silero, kokoro, torch, parselmouth, librosa) are imported lazily inside functions. The backend must boot and the full text loop must work with only `requirements.txt` installed. Never add a top-level import of a heavy dep.
- **8GB VRAM budget:** never pin two 7–8B models. Strategy A: qwen3:4b co-resident with Whisper. Strategy B (default config): qwen3:8b loaded on demand by Ollama. `OLLAMA_MAX_LOADED_MODELS=1`.
- **Delivery analytics are interpretable metrics, not emotion labels.** The `confidence_proxy` and `expressiveness` formulas are documented in `backend/analytics/metrics.py` (`_confidence_proxy`, `_expressiveness`) — keep them transparent. SER stays optional behind `analytics.use_ser` and is surfaced in the UI only as an "experimental" chip, never as a score input.
- Frontend: no runtime CDNs (next/font is build-time self-hosted, allowed), no localStorage, static export only (`output: 'export'`, `trailingSlash: true`). Charts are hand-rolled canvas. Pages: `/` (Home), `/interview`, `/question-bank`, `/dashboard` — any new exported page needs an entry in `backend/main.py`'s `_PAGES` dict so its no-trailing-slash URL resolves. Interview `useSearchParams` requires a `<Suspense>` boundary or the static export build fails.
- Provider abstraction: new LLM backends implement `backend/providers/base.py` and register in `factory.py`. gpt-5* models reject non-default temperature — omit the param.

## Commands

Windows dev machine only has Python 3.14 system-wide, but the voice stack
(`misaki[en]` → `spacy-curated-transformers` → `curated-tokenizers`) has no
Windows wheel for 3.14 yet and needs a C++ toolchain to build from source.
Project venv is pinned to **3.12** instead (uv can fetch it without an admin
install): `uv venv .venv --python 3.12`.

```bash
# one-time setup (from repo root)
uv venv .venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
uv pip install --python .venv/Scripts/python.exe -r requirements-voice.txt
uv pip install --python .venv/Scripts/python.exe nvidia-cudnn-cu12 nvidia-cublas-cu12  # GPU whisper, no system CUDA/cuDNN install needed

# run (from repo root) — ALWAYS via the launcher, never a bare `python -m uvicorn`.
# The launcher refuses to start if .venv is missing instead of silently
# falling back to system Python (which lacks the voice stack entirely — that
# exact mistake previously caused "transcription returns nothing" with no
# error surfaced anywhere). It also sets the ws-ping flags: defaults (20s/20s)
# are too tight for a 30-60s local LLM turn and uvicorn kills the socket with
# 1011 "keepalive ping timeout" otherwise.
./run.ps1                 # PowerShell
run.bat                   # cmd
./run.ps1 -Fake           # offline/canned LLM (run.bat: set PREPPILOT_LLM__PROVIDER=fake & run.bat)

# tests (no GPU/heavy deps needed — 58 tests)
.venv/Scripts/python.exe -m pytest tests/ -q

# frontend
cd frontend && npm install && npm run dev    # dev on :3000 (auto-targets backend :8000)
cd frontend && npm run build                 # rebuild static export → frontend/out (what FastAPI serves)

# local models
ollama pull qwen3:8b                         # ~5.5GB   (qwen3:4b for co-residence)
```

Note on the cuDNN/cuBLAS pip wheels (`backend/audio/stt.py` `_add_cuda_dll_dirs`):
verified empirically that `os.add_dll_directory()` does NOT make ctranslate2
find them on Windows — its CUDA loader only consults `PATH`. The shim
prepends the wheels' `bin/` dirs to `PATH` at first model load instead.

## Verifying changes

1. `.venv/Scripts/python.exe -m pytest tests/ -q`
2. Boot with `PREPPILOT_LLM__PROVIDER=fake` and run a text-mode session end-to-end (create session via UI or POST /api/sessions, answer over WS, expect feedback → next question → report; check /dashboard trends).
3. `cd frontend && npm run build` must stay clean (TS strict).
4. Voice paths (Whisper/VAD/TTS) only run on the GPU machine — test manually there; keep their failure modes non-fatal (status/error WS messages, never a crash). Confirmed working on the 3070: whisper large-v3 int8_float16 uses ~2.1GB VRAM, kokoro TTS synthesizes on CPU.
5. Reconnect: kill the server mid-interview and restart it, then reconnect the same `/ws/session/{id}` — expect a `resumed {answered_count}` message followed by the same still-open question (not a new one at order_idx 0). See `backend/orchestrator.py` `resume()` and `backend/db/repositories.py` `get_resume_state()`.
6. Degradation surfacing: `GET /api/health` returns machine-readable `flags` (`demo_llm`, `stt_missing`, `vad_missing`, `tts_missing`) via `build_health_flags()` — launching with the wrong Python (no voice deps) sets `stt_missing: true` and the UI shows a persistent banner (voice mode stays selectable — only `stt.backend: none` hard-disables it). Empty-transcript guard: recording silence sends `error {code: "empty_transcript"}` and keeps the same question open (no scoring of ""). Both are unit-tested (`tests/test_health.py`, `tests/test_empty_transcript.py`).
7. Manual end-of-turn ("done") calls `TurnDetector.flush(force=True)` so a quiet mic / accent the VAD never flags as speech still gets transcribed rather than silently dropped (`tests/test_vad.py`). Session deletion: `DELETE /api/sessions/{id}` and `DELETE /api/sessions` cascade through the ORM relationships (`tests/test_delete.py`); the dashboard has per-row delete + "Clear all".

## Known limitations / next steps

- `max_questions` override lives in `app.state.session_overrides` (in-memory) — lost on server restart between session creation and WS connect. Fine for now; move to a column if it matters.
- On resume, `InterviewOrchestrator._started_at` is not restored from the DB, so a completed session's `duration_sec` undercounts time spent before a reconnect.
- A retried answer (after a ProviderError during scoring) can leave more than one `Answer` row pointing at the same `Question`; `get_resume_state` picks the most-recently-scored one. The ORM's `Question.answer` relationship (`uselist=False`) isn't used for resume for exactly this reason.
- Ideas: résumé RAG, fine-tuned scoring model, facial-expression track, Modal deployment (stub in `modal/deploy.py`).
