"use client";

/**
 * Shared mic-capture hook: getUserMedia -> AudioContext -> AudioWorklet
 * (public/audio-worklet.js, registers 'pcm-capture') -> downsample to 16kHz
 * mono -> ~200ms Int16 frames, handed to the caller via onFrame. Used by both
 * the practice tab (/interview) and Full Interview (/full-interview) so the
 * capture pipeline only exists once.
 */

import { useCallback, useRef, useState } from "react";

const TARGET_RATE = 16000;
const FRAME_SAMPLES = TARGET_RATE * 0.2; // 200ms => 3200 samples

/** Simple linear-interpolation downsampler (mono). */
function downsample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (toRate >= fromRate) return input;
  const ratio = fromRate / toRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = pos - i0;
    out[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return out;
}

export interface AudioCapture {
  init: () => Promise<void>;
  startRecording: () => void;
  /** Stops streaming; flushes any residual partial frame first. */
  stopRecording: () => void;
  dispose: () => void;
  recording: boolean;
  meterLevelRef: React.RefObject<number>;
}

export function useAudioCapture(opts: { onFrame: (buf: ArrayBuffer) => void }): AudioCapture {
  const onFrameRef = useRef(opts.onFrame);
  onFrameRef.current = opts.onFrame;

  const [recording, setRecording] = useState(false);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const recordingRef = useRef(false);
  const sendBufRef = useRef<number[]>([]); // Int16 samples awaiting a frame
  const meterLevelRef = useRef(0);

  const onAudioChunk = useCallback((float32: Float32Array) => {
    // Update the level meter regardless of recording state.
    let sum = 0;
    for (let i = 0; i < float32.length; i++) sum += float32[i] * float32[i];
    meterLevelRef.current = Math.sqrt(sum / float32.length);

    if (!recordingRef.current) return;
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    const rate = ctx.sampleRate;
    const mono16k = rate === TARGET_RATE ? float32 : downsample(float32, rate, TARGET_RATE);

    // Float32 [-1,1] -> Int16, appended to the pending frame buffer.
    const buf = sendBufRef.current;
    for (let i = 0; i < mono16k.length; i++) {
      const s = Math.max(-1, Math.min(1, mono16k[i]));
      buf.push(s < 0 ? s * 0x8000 : s * 0x7fff);
    }

    // Flush complete ~200ms frames.
    while (buf.length >= FRAME_SAMPLES) {
      const frame = new Int16Array(buf.splice(0, FRAME_SAMPLES));
      onFrameRef.current(frame.buffer);
    }
  }, []);

  const init = useCallback(async () => {
    mediaStreamRef.current = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
    });

    // Prefer a 16 kHz context; some browsers refuse, so fall back to native.
    try {
      audioCtxRef.current = new AudioContext({ sampleRate: 16000 });
    } catch {
      audioCtxRef.current = new AudioContext();
    }
    const audioCtx = audioCtxRef.current;

    await audioCtx.audioWorklet.addModule("/audio-worklet.js");
    sourceNodeRef.current = audioCtx.createMediaStreamSource(mediaStreamRef.current);
    workletNodeRef.current = new AudioWorkletNode(audioCtx, "pcm-capture");
    workletNodeRef.current.port.onmessage = (e: MessageEvent<Float32Array>) =>
      onAudioChunk(e.data);
    sourceNodeRef.current.connect(workletNodeRef.current);
    // Note: worklet output is not connected to destination — capture only.
  }, [onAudioChunk]);

  const startRecording = useCallback(() => {
    if (!audioCtxRef.current) return;
    if (audioCtxRef.current.state === "suspended") {
      audioCtxRef.current.resume();
    }
    recordingRef.current = true;
    sendBufRef.current = [];
    setRecording(true);
  }, []);

  const stopRecording = useCallback(() => {
    if (!recordingRef.current) return;
    recordingRef.current = false;
    if (sendBufRef.current.length > 0) {
      onFrameRef.current(new Int16Array(sendBufRef.current).buffer);
    }
    sendBufRef.current = [];
    setRecording(false);
  }, []);

  const dispose = useCallback(() => {
    stopRecording();
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
  }, [stopRecording]);

  return { init, startRecording, stopRecording, dispose, recording, meterLevelRef };
}
