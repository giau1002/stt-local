class PCM16Capture extends AudioWorkletProcessor {
  constructor() {
    super(); this.samples = new Int16Array(1600); this.count = 0; this.closed = false;
    this.port.onmessage = (event) => {
      if (event.data === 'flush') {
        this.closed = true;
        if (this.count) this.emit();
        this.port.postMessage({type:'flushed'});
      }
    };
  }
  emit() {
    const bytes = new ArrayBuffer(this.count * 2), view = new DataView(bytes);
    for (let i = 0; i < this.count; i++) view.setInt16(i * 2, this.samples[i], true);
    this.port.postMessage({type:'pcm', bytes}, [bytes]); this.count = 0;
  }
  process(inputs) {
    if (this.closed) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let sample = 0;
      for (const channel of channels) sample += channel[i] / channels.length;
      sample = Math.max(-1, Math.min(1, sample));
      this.samples[this.count++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
      if (this.count === this.samples.length) this.emit();
    }
    return true;
  }
}
registerProcessor('pcm16-capture', PCM16Capture);
