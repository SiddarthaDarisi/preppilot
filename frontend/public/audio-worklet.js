/**
 * PrepPilot — AudioWorklet processor for microphone capture.
 *
 * Registers 'pcm-capture'. Accumulates mono Float32 samples from the input
 * and posts them to the main thread in ~2048-sample chunks. The main thread
 * handles downsampling to 16 kHz and Int16 conversion, so this processor
 * stays trivially simple and allocation-light.
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.CHUNK = 2048;
    this.buffer = new Float32Array(this.CHUNK);
    this.offset = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel || channel.length === 0) return true; // keep alive even when silent

    let read = 0;
    while (read < channel.length) {
      const space = this.CHUNK - this.offset;
      const take = Math.min(space, channel.length - read);
      this.buffer.set(channel.subarray(read, read + take), this.offset);
      this.offset += take;
      read += take;

      if (this.offset === this.CHUNK) {
        // Transfer a copy so we can keep reusing our scratch buffer.
        const out = this.buffer.slice(0);
        this.port.postMessage(out, [out.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
