"use strict";

const $ = (id) => document.getElementById(id);
const startButton = $("start");
const stopButton = $("stop");
const uploadButton = $("upload");
const fileInput = $("file");
const languageInput = $("language");
const modeInput = $("mode");
const MAX_BYTES = 10 * 1024 * 1024;
let recorder = null;
let stream = null;
let tick = null;
let deadline = null;
let startedAt = 0;
let busy = false;
let recording = false;
let chunks = [];
let recordingFailed = false;
let meterContext = null;
let analyser = null;
let meterSource = null;
let recordingUrl = null;
let peakLevel = 0;
let realtimeSession = null;

function renderRealtimeResult(message, final = false) {
  const text = final ? message.text : message.full_text;
  $("transcript").textContent = text || "";
  $("placeholder").hidden = Boolean(text);
  $("placeholder").textContent = final ? "这段音频中没有识别到清晰语音。" : "正在等待可识别的语音片段…";
  $("copy").disabled = !text;
  $("duration").textContent = `${Number(message.duration_seconds).toFixed(2)} 秒`;
  $("processing").textContent = `${Number(message.processing_seconds).toFixed(2)} 秒`;
  $("result-language").textContent = message.language === "zh" ? "中文" : "English";
  if (text) {
    const box = document.querySelector(".transcript-wrap");
    box.scrollTop = box.scrollHeight;
  }
}

function endRealtimeCapture() {
  if (recorder && recorder.state !== "inactive") recorder.stop();
  cleanupMicrophone();
}

function updateInputLevel() {
  if (!analyser) return;
  const values = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(values);
  let power = 0;
  let peak = 0;
  for (const value of values) { power += value * value; peak = Math.max(peak, Math.abs(value)); }
  peakLevel = Math.max(peakLevel, peak);
  const rms = Math.sqrt(power / values.length);
  $("input-level").value = Math.min(1, rms * 10);
  $("input-hint").textContent = rms > 0.003 ? "已检测到声音（不代表一定是语音）" : "输入声音很弱或无声，请留意录音回放";
}

async function prepareInputMeter() {
  peakLevel = 0;
  $("input-hint").textContent = `正在使用：${stream.getAudioTracks()[0]?.label || "默认麦克风"}`;
  try {
    meterContext = new AudioContext();
    await meterContext.resume();
    meterSource = meterContext.createMediaStreamSource(stream);
    analyser = meterContext.createAnalyser();
    analyser.fftSize = 2048;
    meterSource.connect(analyser);
  } catch {
    $("input-hint").textContent = "音量检测不可用，录音仍可继续；停止后可回放检查。";
  }
}

function previewRecording(file) {
  const audio = $("recording-audio");
  audio.pause();
  audio.removeAttribute("src");
  if (recordingUrl) URL.revokeObjectURL(recordingUrl);
  recordingUrl = URL.createObjectURL(file);
  audio.src = recordingUrl;
  $("recording-download").href = recordingUrl;
  $("recording-download").download = file.name;
  $("recording-preview").hidden = false;
  const db = peakLevel > 0 ? `${(20 * Math.log10(peakLevel)).toFixed(1)} dBFS` : "未检测到（或音量检测不可用）";
  $("recording-details").textContent = `录音大小 ${(file.size / 1024).toFixed(1)} KiB；采集峰值 ${db}。识别为空时，请先播放确认是否清楚听见讲话。录音仅留在当前页面，刷新后释放。`;
}

function setStatus(state, message) {
  const titles = { idle: "待开始", preparing: "准备中", recording: "录音中", processing: "识别中", complete: "已完成", error: "出错了" };
  $("status-pill").dataset.state = state;
  $("status-pill").textContent = titles[state];
  $("status").textContent = message;
  $("recorder").classList.toggle("recording", state === "recording");
}

function updateControls() {
  startButton.disabled = busy || recording;
  stopButton.disabled = !recording;
  uploadButton.disabled = busy || recording || !fileInput.files.length;
  fileInput.disabled = busy || recording;
  languageInput.disabled = busy || recording;
  modeInput.disabled = busy || recording;
}

function cleanupMicrophone() {
  if (tick) clearInterval(tick);
  if (deadline) clearTimeout(deadline);
  tick = null;
  deadline = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  meterSource?.disconnect();
  meterSource = null;
  analyser = null;
  if (meterContext) meterContext.close().catch(() => {});
  meterContext = null;
  $("input-level").value = 0;
  recording = false;
  updateControls();
}

function resetResult() {
  $("transcript").textContent = "";
  $("placeholder").hidden = false;
  $("placeholder").textContent = "识别出的文字会出现在这里。";
  $("duration").textContent = "—";
  $("processing").textContent = "—";
  $("copy").disabled = true;
  $("result-language").textContent = languageInput.value === "zh" ? "中文" : "English";
}

function explainMicrophone(error) {
  switch (error?.name) {
    case "NotAllowedError": case "PermissionDeniedError": return "麦克风权限被拒绝。请在浏览器地址栏允许访问后重试，或改为上传音频。";
    case "NotFoundError": case "DevicesNotFoundError": return "未检测到可用麦克风。请连接设备后重试。";
    case "NotReadableError": return "无法读取麦克风；设备可能正被其他程序占用。";
    default: return `录音失败：${error?.message || "请检查麦克风与浏览器设置。"}`;
  }
}

function formatTime(seconds) {
  const total = Math.min(60, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

async function submitAudio(file) {
  if (!file.size) { setStatus("error", "音频文件为空，请重新选择。"); return; }
  if (file.size > MAX_BYTES) { setStatus("error", "音频文件不能超过 10 MiB。"); return; }
  busy = true;
  updateControls();
  setStatus("processing", "正在本地识别，请稍候。模型首次加载可能需要更长时间…");
  try {
    const data = new FormData();
    data.append("file", file, file.name);
    data.append("language", languageInput.value);
    const response = await fetch("/api/transcribe", { method: "POST", body: data });
    let result;
    try { result = await response.json(); } catch { throw new Error("服务返回了无效响应，请重试。"); }
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "识别失败，请检查音频或稍后重试。");
    $("result-language").textContent = result.language === "zh" ? "中文" : "English";
    $("duration").textContent = `${Number(result.duration_seconds).toFixed(2)} 秒`;
    $("processing").textContent = `${Number(result.processing_seconds).toFixed(2)} 秒`;
    $("transcript").textContent = result.text || "";
    $("placeholder").hidden = Boolean(result.text);
    if (!result.text) $("placeholder").textContent = "这段音频中没有识别到清晰语音。";
    $("copy").disabled = !result.text;
    setStatus("complete", result.text ? "识别完成，可以复制文字或继续录音。" : "识别完成，但未检测到可识别语音。可重新尝试。");
  } catch (error) {
    setStatus("error", error.message || "请求失败，请检查本地服务后重试。");
  } finally {
    busy = false;
    updateControls();
  }
}

startButton.addEventListener("click", async () => {
  if (busy || recording) return;
  resetResult();
  busy = true;
  updateControls();
  setStatus("preparing", "正在请求麦克风权限…");
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器无法访问麦克风，请使用 localhost 上的 Chrome 或 Edge。");
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    await prepareInputMeter();
    const isRealtime = modeInput.value === "realtime";
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
      .find((type) => MediaRecorder.isTypeSupported(type));
    if (!mime) throw new Error("浏览器不支持 WebM/Opus 或 OGG 录音，请尝试 Chrome 或 Edge。");
    chunks = [];
    recordingFailed = false;
    recorder = new MediaRecorder(stream, { mimeType: mime });
    recorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
    recorder.addEventListener("error", (event) => {
      recordingFailed = true;
      realtimeSession?.cancel();
      busy = false;
      setStatus("error", explainMicrophone(event.error));
      try { if (recorder.state !== "inactive") recorder.stop(); } catch { cleanupMicrophone(); }
    });
    recorder.addEventListener("stop", async () => {
      cleanupMicrophone();
      if (recordingFailed) { busy = false; updateControls(); return; }
      if (!chunks.length) { busy = false; updateControls(); setStatus("error", "录音没有生成有效音频，请重试。"); return; }
      const ext = mime.includes("webm") ? "webm" : "ogg";
      const file = new File(chunks, `recording.${ext}`, { type: mime });
      chunks = [];
      previewRecording(file);
      if (!isRealtime) await submitAudio(file);
    }, { once: true });
    if (isRealtime) {
      setStatus("preparing", "正在准备本地实时模型和连接，准备好后开始计时…");
      realtimeSession = new RealtimeSession({
        update(message) {
          renderRealtimeResult(message);
          setStatus(recording ? "recording" : "processing", recording ? `实时录音中 · 第 ${message.sequence} 段预览已更新，停止后校正最终文字。` : "正在完成最后的识别结果…");
        },
        processing(message) {
          setStatus(recording ? "recording" : "processing", `正在识别第 ${message.sequence} 段${recording ? "，录音继续中…" : "，请稍候…"}`);
        },
        finishing() { setStatus("processing", "采集已结束，正在处理剩余片段，请稍候…"); },
        finalizing() { setStatus("processing", "正在校正整段最终文字，分段预览可能会调整，请稍候…"); },
        limit() { if (recording) stopButton.click(); },
        final(message) {
          endRealtimeCapture();
          renderRealtimeResult(message, true);
          busy = false;
          updateControls();
          setStatus("complete", message.text ? "实时识别已完成，已处理尾段并校正最终文字。可以复制或再次录音。" : "实时识别完成，但没有可识别语音。请回放录音检查输入设备。");
        },
        error(message) {
          endRealtimeCapture();
          busy = false;
          updateControls();
          setStatus("error", `${message} 已显示的分段文字仍保留，可复制；未完成部分不代表识别成功。`);
        },
      });
      await realtimeSession.start(stream, meterContext, languageInput.value);
    } else {
      realtimeSession = null;
    }
    recorder.start(250);
    startedAt = performance.now();
    $("timer").textContent = "00:00";
    recording = true;
    setStatus("recording", isRealtime ? "实时录音中：停顿约 0.6 秒或连续讲话约 4 秒后逐段出字，60 秒自动停止。" : "正在录音。点击 Stop Recording 后才会提交识别。到 60 秒将自动停止。");
    tick = setInterval(() => { $("timer").textContent = formatTime((performance.now() - startedAt) / 1000); updateInputLevel(); }, 200);
    deadline = setTimeout(() => stopButton.click(), 60_000);
  } catch (error) {
    realtimeSession?.cancel();
    cleanupMicrophone();
    setStatus("error", explainMicrophone(error));
  } finally {
    busy = false;
    updateControls();
  }
});

stopButton.addEventListener("click", async () => {
  if (!recording || !recorder || recorder.state === "inactive") return;
  recording = false;
  busy = true;
  updateControls();
  setStatus("preparing", "正在结束录音并整理音频…");
  $("timer").textContent = formatTime((performance.now() - startedAt) / 1000);
  if (tick) clearInterval(tick);
  if (deadline) clearTimeout(deadline);
  if (modeInput.value === "realtime" && realtimeSession) {
    setStatus("processing", "正在发送最后一段音频并等待最终结果…");
    await realtimeSession.stop();
    endRealtimeCapture();
    return;
  }
  try { recorder.stop(); } catch (error) { cleanupMicrophone(); busy = false; setStatus("error", explainMicrophone(error)); updateControls(); }
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  $("selected-file").textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MiB` : "尚未选择文件";
  updateControls();
});
uploadButton.addEventListener("click", () => {
  if (busy || recording || !fileInput.files.length) return;
  resetResult();
  submitAudio(fileInput.files[0]);
});
languageInput.addEventListener("change", () => { if (!busy && !recording && !$("transcript").textContent) $("result-language").textContent = languageInput.value === "zh" ? "中文" : "English"; });
modeInput.addEventListener("change", () => {
  $("mode-hint").textContent = modeInput.value === "realtime"
    ? "实时模式：停顿或每约 4 秒更新预览，停止后校正最终文字；处理耗时为累计推理耗时（含校正）。文件上传仍为普通识别。"
    : "普通模式：停止录音后，一次性提交识别。文件上传始终使用普通识别。";
});
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("transcript").textContent); setStatus("complete", "文字已复制到剪贴板。"); }
  catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents($("transcript"));
    selection?.removeAllRanges();
    selection?.addRange(range);
    setStatus("error", "浏览器限制剪贴板访问，已选中文字。请按 Ctrl+C 复制，或检查浏览器权限。");
  }
});
