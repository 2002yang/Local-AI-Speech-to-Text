# 系统设计

## 架构

```text
Chrome/Edge (HTML/CSS/JS + getUserMedia + MediaRecorder)
    ├─ 录音结束 → WebM/Opus ───┐
    └─ 文件上传 → WAV/WebM/OGG ─┴─ POST /api/transcribe
                                    │
                    FastAPI: 参数/大小/格式校验
                                    ↓
                    PyAV 解码 → 16 kHz 单声道 float32
                                    ↓
                    检查实际时长 → ≤ 20 秒低能量边界分段
                                    ↓
                    sherpa-onnx + SenseVoiceSmall ONNX INT8
                    (CPU、固定中文或英文识别器、复用模型)
                                    ↓
                    JSON 结果 → 浏览器文本/状态/耗时
```

`app/main.py` 定义接口；`app/audio.py` 统一解码和时长控制；`app/asr.py` 管理模型；`app/config.py` 保存路径和限制；`static/` 是无 Node 构建的原生前端；`scripts/download_model.py` 显式准备项目内模型。应用启动和 `/health` 不下载或加载权重。

## 选型

SenseVoiceSmall 的 ONNX INT8 转换由 sherpa-onnx 发布，支持中文普通话和英语，API 的 `language` 可以明确指定 `zh` / `en`；非自回归推理在普通 CPU 上较轻。两个识别器按语言懒加载并分别复用，锁保护共享推理以防单机并发冲突。依赖通过 pip 安装，模型在项目目录 `models/sensevoice-small-int8/`。

模型来源：[sherpa-onnx SenseVoice 预训练模型](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)、[SenseVoice 官方项目](https://github.com/FunAudioLLM/SenseVoice)。原始权重作者：阿里巴巴集团 / FunASR / SenseVoice 团队；权重遵守 [FunASR Model Open Source License Agreement v1.1](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)，需标注出处、作者并保留模型名称；运行时代码的许可证与模型许可分开。脚本核对模型和词表 SHA-256。本项目不把权重提交源码。

未选择 Qwen3-ASR-0.6B ONNX：该模型可用于 CPU，但不同 ONNX 转换版的推理代码和指定语言方式差异较大，这道题只需中英短音频，优先选部署链路更短的 SenseVoice。AIAvatarKit 的默认示例有云端 STT/LLM/TTS 组件，不适合作为本题系统底座。

## 音频和时长

- 限 10 MiB 原始上传大小，采用有界读取，拒绝缺失字段、空文件、不支持扩展名、错误容器及编码；真实解码失败返回 4xx。
- PyAV 在 Python wheel 中封装 FFmpeg 库，不依赖系统 `ffmpeg` 可执行文件。一次只处理一条音轨，解码帧逐段检查 65 秒上限；重采样为 16 kHz 单声道。实际时长由原始音频解码帧数计算，不以文件大小或录音计时器推断。
- 识别前按约 20 秒切分，在 18–22 秒附近选择短窗口中能量最低的位置；无停顿时仍可能在词中间切分，属于已知边界，真实长语音需继续检查。静音段不送模型，避免无语音幻觉。每段语言保持一致，中文直接合并，英文段间加空格。
- `processing_seconds` 在接收处理请求时开始，包含本次读取、解码、重采样、模型加载及推理，不含权重下载；首次模型加载会增加第一次请求耗时。
- 后端受控线程池运行解码和模型推理，应用主事件循环不直接做同步推理。无长期持久化音频。

## 错误与限制

FastAPI 参数错误使用 422；空或损坏的音频 400；不支持格式 415；超上传大小 413；时长超 65 秒 400；本地模型缺失/加载失败 503；推理异常 500。向用户返回可理解的信息，不返回内部堆栈。 `/health` 返回 `{"status":"ok"}` 只表示 HTTP 服务响应，不能视为模型已就绪。

## 实时识别（F6 可选加分）

`static/realtime.js` 管理实时会话，`static/pcm-worklet.js` 将浏览器音频混为单声道并重采样为 16 kHz PCM16，每 100 ms 发送一次。`app/realtime.py` 提供 WebSocket `/api/realtime`，复用 `app/asr.py` 的本地 CPU 模型。普通录音和上传继续使用规定的 POST 接口。

协议顺序：

1. 客户端发送 `{"type":"start","language":"zh","sample_rate":16000,"format":"pcm_s16le"}`，语言也可为 `en`。
2. 后端准备对应语言模型并返回 `ready`，客户端开始发送二进制 PCM16 little-endian 音频。
3. 后端返回 `processing` 和有序 `segment`（含 `sequence`、`text`、`full_text`、语言、时长及累计推理耗时）。页面以 `full_text` 更新预览。
4. 客户端停止时先刷新尾部 PCM，再发送 `{"type":"stop"}`。后端发出 `finishing`，处理剩余片段，再以 `finalizing` 提示全文校正；`final.text` 替换预览并结束会话。达到时长上限发 `limit`，异常发 `error`。

分段采用简单能量门控：100 ms 分析帧、RMS 阈值 0.0006、0.2 秒前置缓冲、0.6 秒静音结束一段；连续语音最多缓存 4 秒，在最后一秒选择低能量边界。这不是神经网络 VAD，噪声和无停顿断词仍可能影响预览。停止后额外对完整音频识别一次恢复上下文，不在每次预览时重复识别全部历史。

资源限制：采集及服务端音频上限 60 秒，单消息不超过 16000 字节，待推理队列最多 4 段，客户端发送积压超过约 2 秒时报错；服务端接收空闲超时 15 秒、采集会话墙钟上限 75 秒。校正所需完整音频最多约 3.84 MB float32 数据。断连取消会话任务，浏览器停止音频节点及麦克风轨道。

实时 `duration_seconds` 按收到的 PCM 样本数计算，包含静音；实时 `processing_seconds` 为分段与最终校正的累计推理调用耗时（含等待模型锁），不含录音等待和 `ready` 前的模型准备。因此它不是首字延迟，也不是普通 POST 请求端到端处理时间。短片段出字还需分段等待和实际推理，未承诺固定延迟。
