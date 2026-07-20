# Deploying PrepPilot

PrepPilot is a server app (FastAPI + WebSockets + optional GPU voice stack), so it does
**not** run on static hosts like GitHub Pages. This guide covers the two things that *do*
work for free:

1. **Source on GitHub** — version control + the public "here is the whole project" link.
2. **A free live text-mode demo** on Hugging Face Spaces — a clickable, working demo with
   **no GPU, no API key, and $0 cost**.

Voice mode (Whisper + Kokoro TTS) needs a local GPU and is best shown with a short screen
recording; see the [README](README.md) to run the full voice loop locally.

---

## 1. Publish the source to GitHub

```bash
cd preppilot
git init -b main
git add -A
git status          # confirm .venv/, data/, preppilot.db, node_modules/ are NOT listed
git commit -m "Initial commit: PrepPilot — local-first AI mock-interview tutor"

# create the public repo and push (GitHub CLI)
gh repo create <you>/preppilot --public --source=. --remote=origin --push \
  --description "Local-first AI mock-interview tutor: STT → LLM coaching → prosody analytics → TTS."
```

`.gitignore` already excludes secrets and generated files (`.venv/`, `.env`, `data/`,
`preppilot.db`, `__pycache__/`, `frontend/node_modules/`, `frontend/.next/`,
`frontend/out/`). There are **no API keys in the repo** — providers read them from env vars.

---

## 2. Free live demo (text mode)

The existing [`Dockerfile`](Dockerfile) is a CPU image: it builds the Next.js static export
and serves it plus the API from uvicorn on port 8000. On a free host we run the backend in
**text-only mode** — the `fake` LLM provider gives canned-but-realistic coaching, and the
voice backends are disabled so nothing tries to load Whisper/Kokoro on a GPU-less box. The
runtime footprint is a lightweight FastAPI process (well under the 512 MB free-tier limit;
`requirements-voice.txt` is **not** installed by this Dockerfile).

Pick a host with **WebSocket + Docker support and a real free tier**:

| Host | Free tier | Idle behavior | Credit card |
|---|---|---|---|
| **Render** (simplest) | 750 hrs/mo, 512 MB | Sleeps after 15 min → ~30–50 s cold start | Not required |
| **Koyeb** | 1 web service, 512 MB | **No sleep** (always on) | Not required in most regions |
| Hugging Face Spaces | Docker Spaces now require **PRO ($9/mo)** — only *static* Spaces are free | — | — |

> ⚠️ **Fly.io** and **HF Docker Spaces** are no longer free. The `deploy/hf-space-README.md`
> header is kept for anyone who *does* have HF PRO (push the repo to a Docker Space and it
> works as-is).

### 2a. Deploy on Render (recommended, free)

1. Sign in at <https://render.com> with GitHub.
2. **New → Web Service** → connect the `preppilot` repo.
3. Render auto-detects the `Dockerfile` (or the [`render.yaml`](render.yaml) blueprint, which
   already sets the env below). Instance type = **Free**. Create.
4. Wait for the build; the demo lives at `https://preppilot-XXXX.onrender.com`.

The included [`render.yaml`](render.yaml) makes this a **Blueprint** deploy: New → Blueprint →
pick the repo and Render reads the env + Docker config automatically.

### 2b. Deploy on Koyeb (free, no cold starts)

1. Sign in at <https://koyeb.com> with GitHub.
2. **Create Web Service** → GitHub → `preppilot` repo → builder **Dockerfile**.
3. Set the env vars from §2c, port **8000**, instance **Free**. Deploy.
4. Demo lives at `https://preppilot-<org>.koyeb.app`.

### 2c. The env vars that make it text-only

| Variable | Value | Why |
|---|---|---|
| `PREPPILOT_LLM__PROVIDER` | `fake` | Canned coaching — no GPU, no API key |
| `PREPPILOT_STT__BACKEND` | `none` | Don't try to load Whisper on CPU |
| `PREPPILOT_TTS__BACKEND` | `none` | Don't try to load Kokoro |
| `PREPPILOT_VAD__BACKEND` | `none` | No mic turn-detection in text mode |
| `PREPPILOT_SERVER__HOST` | `0.0.0.0` | Bind for the container (Dockerfile also sets this) |

### 2d. Optional: real Claude coaching instead of canned answers

The `fake` provider is free and always works. To upgrade the demo to *real* LLM feedback,
add an API key as a **secret env var** in the host's dashboard (Render: *Environment* →
*Secret*; Koyeb: *Environment variables* → *Secret*):

- Secret `ANTHROPIC_API_KEY` = your key, and change `PREPPILOT_LLM__PROVIDER` to `anthropic`
  (Claude Haiku 4.5), **or** `OPENAI_API_KEY` + `PREPPILOT_LLM__PROVIDER=openai`.

This costs a few cents per session, not dollars. Keep it as a **secret** (not a plain
variable) so the key never appears in the repo, build logs, or the service's public config.

---

## 3. Verify the demo

Open the deployed URL and run one interview end-to-end in **text mode**:

1. Pick a role/seniority on the setup screen → start.
2. Type an answer, submit → expect rubric feedback → the next question → a final report.
3. Check `/dashboard` — the session and its trend point should appear.
4. In browser devtools → Network, confirm the WebSocket connects to the deployed host
   (`wss://<your-app-host>/...`) and there are **no** calls to `127.0.0.1`.

`GET /api/health` returns the degradation flags — on the demo, `stt_missing` and
`tts_missing` are `true` (voice disabled) while the text loop is fully functional.

> On the free tier the first request after ~15 min idle (Render) cold-starts in ~30–50 s —
> normal for a portfolio demo. Koyeb's free tier stays warm.
