# Portfolio Artifact — PrepPilot

> Paste-ready artifact entry for the AIML-500 professional portfolio. Fill in the one
> placeholder — `{{VIDEO_LINK}}` (your demo recording) — then drop this into your portfolio
> site (Google Sites / Wix / GitHub Pages). Keep the **Reflection** out of the public site;
> submit it to Brightspace.

---

## Title
**PrepPilot — A Local-First AI Mock-Interview Tutor**

## Introduction
PrepPilot is a full-stack AI application that runs a realistic mock interview and coaches the
candidate on both **what** they say and **how** they say it. Unlike a chatbot, it listens to
delivery — pace, pauses, filler words, and vocal energy — and returns structured, rubric-based
feedback, entirely offline on a laptop GPU.

## Description
A candidate picks a role, seniority, and (optionally) pastes a job description. An AI
interviewer asks one question at a time, listens to the spoken answer, transcribes it with
word-level timing, analyzes delivery, and scores the response on a 1–10 rubric (content,
structure/STAR, specificity, technical accuracy, delivery) with concrete rewrites. It then
either asks a targeted follow-up or moves on, and finally produces a printable report and a
cross-session trends dashboard. The whole loop — speech-to-text, coaching, analytics, and a
text-to-speech interviewer voice — runs locally; a single config line swaps the LLM to a
cloud API.

## Objective
To demonstrate the ability to design and ship a **complete, production-shaped AI system** —
not a notebook or a single prompt — that integrates real-time audio, multiple ML models, and
an LLM under a hard resource budget (8 GB VRAM), while making thoughtful engineering
trade-offs around reliability, cost, and privacy.

## Process
1. **Designed the contract first** — Pydantic schemas + a documented WebSocket protocol
   shared between a FastAPI backend and a TypeScript frontend.
2. **Built the turn state machine** — a transport- and provider-agnostic orchestrator that
   both the live WebSocket path and the REST endpoints drive.
3. **Assembled the audio pipeline** — Silero VAD turn detection → faster-whisper large-v3
   transcription (word timestamps) → prosody/filler analytics → Kokoro TTS reply.
4. **Made the LLM swappable** — a provider abstraction (Ollama / Anthropic / OpenAI / a
   canned "fake" provider) with automatic fallback, all output parsed as strict JSON.
5. **Engineered for graceful degradation** — every heavy dependency is imported lazily so
   the app boots and the full text loop works with zero ML dependencies installed.
6. **Tested and documented** — 58 GPU-free unit tests, a system-design document, and a free
   cloud text-mode demo deployed via Docker.

## Tools and Technologies Used
- **Backend:** Python, FastAPI, WebSockets, SQLAlchemy 2.0, SQLite, Pydantic
- **AI / ML:** Ollama (qwen3), Claude Haiku 4.5 / GPT-5 mini (cloud option), faster-whisper
  (STT), Silero VAD, Kokoro TTS, parselmouth + librosa (prosody analytics)
- **Frontend:** Next.js 14 (App Router), TypeScript, static export, hand-rolled canvas charts
- **Infra / tooling:** Docker, Render / Koyeb (free demo host), GitHub, pytest, uv

## Value Proposition
*(Artifact-specific value proposition)* **PrepPilot gives job seekers a private, unlimited,
judgment-free way to rehearse interviews and get concrete feedback on their delivery — the
part generic AI chat tools ignore — without sending their voice to the cloud.**

## Unique Value
Most "AI interview" tools grade the transcript. PrepPilot treats **delivery as a first-class
signal** using *interpretable* metrics (documented `confidence_proxy` and `expressiveness`
formulas) rather than black-box emotion labels — and it does this **local-first**, so the
candidate's voice never leaves their machine. Fitting real-time STT + an 8B LLM + TTS inside
an 8 GB VRAM budget, with graceful CPU-only degradation, is the core engineering achievement.

## Relevance
Interviewing under pressure is a near-universal professional bottleneck, and delivery is
where strong candidates most often lose points. As an artifact, PrepPilot demonstrates
end-to-end AI/ML systems engineering — real-time inference, model orchestration, resource
budgeting, and reliable UX — the exact skill set an AI/ML practitioner is hired for.

## Demo & Source
- **Demo video (full voice loop):** {{VIDEO_LINK}}
- **Source code:** https://github.com/SiddarthaDarisi/preppilot
- **System design:** https://github.com/SiddarthaDarisi/preppilot/blob/main/docs/ARCHITECTURE.md

## References
- faster-whisper (CTranslate2), Silero VAD, Kokoro-82M TTS, Ollama, parselmouth (Praat),
  librosa — see `requirements.txt` / `requirements-voice.txt` in the repo for exact versions.

---

### Reflection (for Brightspace — do NOT put this on the public portfolio)
- **Customization for the audience:** _How did you tailor this artifact for reviewers /
  employers?_
- **Lessons learned:** _e.g., fitting multiple models in 8 GB VRAM; why graceful degradation
  and lazy imports mattered; designing the shared schema contract first._
- **Feedback and revisions:** _What feedback did you get and how did you incorporate it?_
