---
title: PrepPilot — AI Mock Interview Tutor
emoji: 🎙️
colorFrom: indigo
colorTo: teal
sdk: docker
app_port: 8000
pinned: false
short_description: Local-first AI mock-interview tutor (text-mode demo)
---

# PrepPilot — live text-mode demo

This Space runs the **text-only** interview loop of
[PrepPilot](https://github.com/SiddarthaDarisi/preppilot): pick a role, answer questions by
typing, and get structured 1–10 rubric coaching (content, structure/STAR, specificity,
technical accuracy, delivery) plus a final report and a trends dashboard.

It runs on a **free CPU Space** with the canned `fake` LLM provider — no GPU and no API key
required. The full experience — spoken answers, faster-whisper transcription, delivery
analytics (WPM / pauses / fillers / pitch), and a Kokoro TTS interviewer voice — needs a
local GPU; see the repo's README and the demo video.

> **Demo mode:** coaching responses here are canned. To see real LLM feedback, the app owner
> can add an `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) Space secret and switch the provider.

## Config (set as Space variables)

```
PREPPILOT_LLM__PROVIDER=fake
PREPPILOT_STT__BACKEND=none
PREPPILOT_TTS__BACKEND=none
PREPPILOT_VAD__BACKEND=none
PREPPILOT_SERVER__HOST=0.0.0.0
```

Source & full documentation: <https://github.com/SiddarthaDarisi/preppilot>
