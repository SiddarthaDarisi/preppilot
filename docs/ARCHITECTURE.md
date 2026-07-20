# PrepPilot — System Design

This document explains **how PrepPilot is built and why**. It is the engineering
companion to the [README](../README.md): the README tells you what the app does and how to
run it; this one walks through the architecture, the data flow of a single interview turn,
and the design decisions that shaped the system.

## 1. The problem

Most "AI interview" tools grade *what* you say. Real interviewers also react to *how* you
say it — pace, hesitation, filler words, monotone delivery. PrepPilot closes that gap while
staying **local-first**: the entire loop (speech-to-text, coaching, analytics,
text-to-speech) can run offline on an 8 GB laptop GPU, and swap to cloud LLM APIs with a
single config line. That constraint — "must run on a 3070, must degrade to a keyboard on a
machine with no GPU" — drove almost every decision below.

## 2. High-level architecture

```mermaid
flowchart TD
    subgraph Browser["Browser — Next.js static export"]
        UI[Setup / Interview / Question-bank / Dashboard]
        MIC[Mic capture → 16 kHz mono PCM16]
    end

    subgraph Server["FastAPI backend (backend/main.py)"]
        WS["WebSocket /ws/session/{id}"]
        ORCH[orchestrator.py — async turn state machine]
        VAD[audio/vad.py — Silero VAD + energy fallback]
        STT[audio/stt.py — faster-whisper large-v3]
        AN[analytics/ — prosody • fillers • confidence proxy]
        LLM[providers/ — ollama | anthropic | openai | fake]
        TTS[audio/tts.py — Kokoro voice]
        DB[(SQLite via SQLAlchemy 2.0)]
    end

    UI -- REST /api/* --> WS
    MIC -- binary PCM frames --> WS
    WS <--> ORCH
    ORCH --> VAD --> STT --> AN
    AN --> LLM --> TTS
    ORCH <--> DB
    TTS -- JSON + audio --> UI
```

Two transports drive the **same** orchestrator:

- **WebSocket** (`/ws/session/{id}`) — binary frames are 16 kHz mono PCM16 mic audio; JSON
  frames are control + results. This is the live interview path.
- **REST** (`/api/*`) — session creation, question-bank generation, history, trends, and
  settings. The dashboard and setup screens are pure REST.

The frontend is a **static export** served by the backend itself, so the browser talks to
one origin. `frontend/src/lib/api.ts` derives the API/WS base from
`window.location` — `""` for REST and `wss://<host>` for the socket — which is why the same
build runs locally, in Docker, and on a hosted demo with **no code change**.

## 3. Anatomy of one interview turn

1. **Capture** — the browser streams PCM16 frames over the WebSocket while the candidate
   speaks (`frontend/src/lib/audioCapture.ts`, `lib/ws.ts`).
2. **Turn detection** — `audio/vad.py` (Silero, with an energy-threshold fallback) watches
   for ~1 s of trailing silence to decide the answer is finished. A manual "Done answering"
   calls `TurnDetector.flush(force=True)` so a quiet mic or an accent the VAD never flags
   still gets transcribed instead of being silently dropped.
3. **Transcription** — `audio/stt.py` runs faster-whisper large-v3 (INT8) and **requires
   word timestamps**, because the analytics layer needs per-word timing.
4. **Delivery analytics** — `analytics/` computes WPM, pause ratio, long pauses, filler
   rate, pitch variance, and energy dynamics (parselmouth + librosa), then the documented
   `confidence_proxy` and `expressiveness` composites. These are **interpretable metrics,
   not emotion labels** (see §5.3).
5. **Coaching** — the active LLM provider (`providers/`) scores the answer against a 1–10
   rubric (content, structure/STAR, specificity, technical accuracy, delivery) and either
   asks a targeted follow-up or moves to the next question. All LLM output is **strict JSON**
   parsed by `complete_json()`, which strips ```` ``` ```` fences and `<think>` blocks and
   retries once on a validation failure.
6. **Voice reply** — `audio/tts.py` (Kokoro, on CPU) synthesizes the interviewer's next
   question; instant rule-based alerts (pace/filler/monotone) reach the UI seconds before
   the fuller LLM feedback.
7. **Persistence** — the session, questions, answers, and scores are written to SQLite so
   the dashboard can chart cross-session trends and the interview can survive a restart.

## 4. Module map

| Path | Responsibility |
|---|---|
| `backend/main.py` | REST + WebSocket transport; serves the static frontend; `/api/health` degradation flags |
| `backend/orchestrator.py` | Transport- and provider-agnostic async turn state machine; resume/reconnect |
| `backend/schemas.py` | **The shared contract** — Pydantic models + the WS protocol; mirrored in `frontend/src/lib/types.ts` |
| `backend/config.py` | Settings: env (`PREPPILOT_*`) > `.env` > `config.yaml` > defaults |
| `backend/providers/` | LLM backends behind one interface + a factory with fallback |
| `backend/prompts/` | Interviewer, coaching (rubric + STAR), report, question-bank generation |
| `backend/audio/` | `vad` (turn detection), `stt` (Whisper), `tts` (Kokoro) |
| `backend/analytics/` | Prosody, fillers, optional SER, and the composite metrics |
| `backend/db/` | SQLAlchemy models + repositories |
| `frontend/` | Next.js App Router, TypeScript, static export, hand-rolled canvas charts |

## 5. Key design decisions

### 5.1 Graceful degradation is non-negotiable
Every heavy dependency (faster-whisper, silero, kokoro, torch, parselmouth, librosa) is
imported **lazily, inside the function that uses it** — never at module top level. The
backend must boot and the full **text** loop must work with only `requirements.txt`
installed. This is what makes the free hosted demo possible: the exact same code runs on a
CPU-only container by setting `stt/tts/vad` backends to `none`. `/api/health` returns
machine-readable flags (`demo_llm`, `stt_missing`, `vad_missing`, `tts_missing`) so the UI
can show an honest banner instead of failing silently.

### 5.2 The 8 GB VRAM budget
Two 7–8B models are never pinned at once. Two strategies fit the budget:
- **A — co-resident:** `qwen3:4b` (~2.5 GB) + Whisper large-v3 INT8 (~3.5 GB) both stay hot.
- **B — sequential (default):** `qwen3:8b` (~5.5 GB) is loaded on demand by Ollama between
  turns, with `OLLAMA_MAX_LOADED_MODELS=1`.

### 5.3 Analytics are interpretable, not black-box emotion labels
`confidence_proxy` and `expressiveness` are transparent formulas documented in
`analytics/metrics.py`. Speech-emotion recognition (SER) is available but **off by default**
and surfaced only as an "experimental" chip — never as a score input — because acted-dataset
SER models are a weak signal and the interpretable prosody metrics are the primary story.

### 5.4 Provider abstraction with fallback
New LLM backends implement `providers/base.py` and register in `factory.py`. `config.yaml`
switches between local Ollama and Anthropic/OpenAI; if the local provider is unreachable at
startup the factory falls back to the configured `fallback_provider`, and a canned `fake`
provider guarantees the flow is always demoable with no GPU and no API key.

### 5.5 Static frontend, served by the backend
`output: 'export'`, `trailingSlash: true`, no runtime CDNs, no localStorage, charts
hand-rolled on canvas. The server is the source of truth (a page reload re-reads state from
`/api/*`). Each exported page needs an entry in `main.py`'s `_PAGES` map so its
no-trailing-slash URL resolves.

### 5.6 Reconnect as a first-class case
The orchestrator's `resume()` (backed by `db/repositories.py:get_resume_state()`) lets a
client reconnect to `/ws/session/{id}` mid-interview after a server restart and receive a
`resumed {answered_count}` message followed by the *same* still-open question — not a fresh
question at index 0.

## 6. Testing & verification

- **58 unit tests** (`tests/`) run with **no GPU and no ML deps** — they cover analytics,
  VAD flush behavior, health flags, the empty-transcript guard, cascade deletes, and resume.
- The canonical smoke test boots with `PREPPILOT_LLM__PROVIDER=fake` and runs a text session
  end-to-end (create → answer over WS → feedback → next question → report → dashboard trend).
- Voice paths (Whisper/VAD/TTS) are validated manually on the GPU machine; their failure
  modes are always non-fatal (status/error WS messages, never a crash).

## 7. What's next

Video / facial-expression track · a fine-tuned scoring model · RAG over the candidate's
résumé · a hosted GPU demo on Modal (the serverless STT stub lives in `modal/deploy.py`).
