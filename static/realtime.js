"use strict";

/* One WebSocket + one AudioWorklet per recording; no retries that duplicate audio. */
class RealtimeSession {
  constructor(callbacks) {
    this.callbacks = callbacks;
    this.socket = null;
    this.node = null;
    this.source = null;
    this.sink = null;
    this.timeout = null;
    this.done = false;
    this.stopping = false;
    this.lastSequence = 0;
    this.flushResolve = null;
    this.rejectReady = null;
    this.serverFinishing = false;
  }

  async start(stream, context, language) {
    if (!context?.audioWorklet) throw new Error("实时模式需要支持 AudioWorklet 的 Chrome/Edge，请改用普通识别。");
    await context.audioWorklet.addModule("/static/pcm-worklet.js");
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${location.host}/api/realtime`);
    try {
      await new Promise((resolve, reject) => {
        this.rejectReady = reject;
        this.timeout = setTimeout(() => this.fail("实时模型准备超时，请检查服务或改用普通识别。"), 45_000);
        this.socket.onopen = () => this.socket.send(JSON.stringify({ type: "start", language, sample_rate: 16000, format: "pcm_s16le" }));
        this.socket.onerror = () => this.fail("实时连接失败，请检查本地服务后重试。");
        this.socket.onclose = () => { if (!this.done) this.fail("实时连接已中断，未完成的录音不会自动重试。请重新录音。"); };
        this.socket.onmessage = (event) => {
          let message;
          try { message = JSON.parse(event.data); } catch { this.fail("实时服务返回了无效消息。"); return; }
          if (message.type === "ready") {
            clearTimeout(this.timeout);
            this.rejectReady = null;
            resolve();
          } else if (message.type === "segment") {
            if (message.sequence !== this.lastSequence + 1) { this.fail("实时识别结果顺序异常，请重新录音。"); return; }
            this.lastSequence = message.sequence;
            this.callbacks.update(message);
          } else if (message.type === "processing") {
            this.callbacks.processing(message);
          } else if (message.type === "finalizing") {
            this.callbacks.finalizing?.();
          } else if (message.type === "finishing") {
            this.serverFinishing = true;
            this.callbacks.finishing();
          } else if (message.type === "limit") {
            this.callbacks.limit();
          } else if (message.type === "final") {
            this.done = true;
            clearTimeout(this.timeout);
            this.disconnectCapture();
            this.callbacks.final(message);
            this.socket.close();
          } else if (message.type === "error") {
            this.fail(message.message || "实时识别失败，请重试。");
          }
        };
      });
      if (this.done) throw new Error("实时会话已结束。");
      this.source = context.createMediaStreamSource(stream);
      this.node = new AudioWorkletNode(context, "pcm-capture");
      this.node.onprocessorerror = () => this.fail("实时音频采集发生错误，请重新录音或改用普通识别。");
      this.sink = context.createGain();
      this.sink.gain.value = 0; // keep capture running without playing microphone audio
      this.node.port.onmessage = (event) => {
        const message = event.data;
        if (message.type === "flushed") {
          this.flushResolve?.();
          return;
        }
        if (message.type === "limit") { this.callbacks.limit(); return; }
        if (message.type !== "pcm" || this.done || this.socket.readyState !== WebSocket.OPEN) return;
        if (this.socket.bufferedAmount > 16000 * 2 * 2) {
          this.fail("音频发送积压超过 2 秒，录音已停止，请重试或改用普通识别。");
          return;
        }
        this.socket.send(message.buffer);
      };
      this.source.connect(this.node);
      this.node.connect(this.sink);
      this.sink.connect(context.destination);
    } catch (error) {
      this.cancel();
      throw error;
    }
  }

  async stop() {
    if (this.done || this.stopping) return;
    this.stopping = true;
    try {
      if (this.node) {
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => { this.flushResolve = null; reject(new Error("实时音频收尾超时，请重新录音。")); }, 3000);
          this.flushResolve = () => { clearTimeout(timer); this.flushResolve = null; resolve(); };
          this.node.port.postMessage({ type: "stop" });
        });
      }
      this.disconnectCapture();
      if (this.done || this.socket?.readyState !== WebSocket.OPEN) return;
      if (!this.serverFinishing) this.socket.send(JSON.stringify({ type: "stop" }));
      this.timeout = setTimeout(() => this.fail("实时识别尾段处理超时，请重试。"), 60_000);
    } catch (error) { this.fail(error.message); }
  }

  disconnectCapture() {
    this.source?.disconnect();
    this.node?.disconnect();
    this.sink?.disconnect();
    this.source = null;
    this.node = null;
    this.sink = null;
  }

  fail(message) {
    if (this.done) return;
    this.done = true;
    clearTimeout(this.timeout);
    this.rejectReady?.(new Error(message));
    this.rejectReady = null;
    this.disconnectCapture();
    this.socket?.close();
    this.callbacks.error(message);
  }

  cancel() {
    this.done = true;
    clearTimeout(this.timeout);
    this.disconnectCapture();
    this.socket?.close();
  }
}
