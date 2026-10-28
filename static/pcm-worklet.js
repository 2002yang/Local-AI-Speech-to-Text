/* Capture only: bounded 16kHz mono PCM16 packets, no recognition in the browser. */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.samplesPerOutput = sampleRate / 16000;
    this.remaining = this.samplesPerOutput;
    this.weighted = 0;
    this.packet = new Int16Array(1600); // 100 ms
    this.used = 0;
    this.total = 0;
    this.finished = false;
    this.port.onmessage = (event) => {
      if (event.data?.type === "stop") {
        this.finished = true;
        this.flush();
        this.port.postMessage({ type: "flushed" });
      }
    };
  }

  flush() {
    if (!this.used) return;
    const packet = this.packet.slice(0, this.used);
    this.port.postMessage({ type: "pcm", buffer: packet.buffer }, [packet.buffer]);
    this.used = 0;
  }

  process(inputs) {
    if (this.finished || !inputs[0]?.length) return true;
    const channels = inputs[0];
    for (let index = 0; index < channels[0].length; index++) {
      let sample = 0;
      for (const channel of channels) sample += channel[index] / channels.length;
      let available = 1;
      while (available > 1e-8) {
        const weight = Math.min(available, this.remaining);
        this.weighted += sample * weight;
        this.remaining -= weight;
        available -= weight;
        if (this.remaining < 1e-8) {
          const value = Math.max(-1, Math.min(1, this.weighted / this.samplesPerOutput));
          this.packet[this.used++] = Math.round(value * (value < 0 ? 32768 : 32767));
          this.total++;
          this.remaining = this.samplesPerOutput;
          this.weighted = 0;
          if (this.used === this.packet.length) this.flush();
          if (this.total >= 16000 * 60) {
            this.finished = true;
            this.flush();
            this.port.postMessage({ type: "limit" });
            return true;
          }
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
