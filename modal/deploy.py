"""Phase-5 stub: Modal serverless GPU deployment for the STT (+ optional SER) pipeline.

Not wired into the local app — the local build is the focus. When you're ready to
host the demo (spec §5), this is the shape of it:

    pip install modal
    modal setup
    modal deploy modal/deploy.py

Design (per spec):
- faster-whisper large-v3 INT8 on an L4 ($0.000222/s), weights cached in a Modal
  Volume so cold starts are 3-15s instead of a full HF download.
- scale-to-zero: ~50 sessions/month lands around $1-3, inside Modal's $30 free credit.
- The FastAPI app stays wherever you host it (or as a Modal ASGI app); it calls
  these functions instead of the local backend.audio.stt path.
"""
import modal

app = modal.App("preppilot-stt")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("faster-whisper>=1.2.0", "numpy")
)

weights = modal.Volume.from_name("preppilot-weights", create_if_missing=True)


@app.function(image=image, gpu="L4", volumes={"/models": weights}, timeout=120)
def transcribe(pcm16: bytes, sample_rate: int = 16000) -> dict:
    """Transcribe a single utterance; returns TranscriptionResult-shaped dict."""
    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel(
        "large-v3", device="cuda", compute_type="int8_float16", download_root="/models"
    )
    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    segments, info = model.transcribe(audio, beam_size=5, word_timestamps=True)
    words, texts = [], []
    for seg in segments:
        texts.append(seg.text)
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return {
        "text": " ".join(t.strip() for t in texts).strip(),
        "words": words,
        "language": info.language,
        "duration_sec": len(audio) / sample_rate,
    }
