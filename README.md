# Local AI Speech-to-Text

源码仓库：https://github.com/2002yang/Local-AI-Speech-to-Text

基于浏览器录音和本地开源 AI 的中英文语音识别面试项目。FastAPI 提供页面与 API；SenseVoiceSmall ONNX INT8 在 Windows CPU 上通过 sherpa-onnx 推理。识别无需云端 ASR、不保存历史。

## 环境

- Windows 11 x64、Python **3.12**、Chrome / Edge 最新稳定版、普通 CPU。
- 首次准备模型时需要网络；准备完成后推理可离线。
- Python 运行文件、权重、样本都在本项目目录下；无需 Node.js、Docker、数据库或 GPU。
- 浏览器访问 `http://127.0.0.1:8000`，本机 localhost 无需 HTTPS 即可请求麦克风。

## 安装与模型初始化

建议先在项目根目录创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

应显示 Python 3.12。若当前 `python` 不是 3.12，请改用已安装的 Python 3.12 解释器创建环境。

```powershell
python -m pip install -r requirements.txt
python -m scripts.download_model
```

初始化脚本从 [sherpa-onnx 官方发布资源](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models)下载 `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2`，仅提取 `model.int8.onnx` 和 `tokens.txt` 到 `models/sensevoice-small-int8/`。请记录脚本输出的 SHA-256，模型权重不随源码提交。模型目录留在项目根目录下；启动和常规测试均不会自行下载模型。若下载失败，可重试初始化脚本；模型文件缺失时 API 返回 503。

模型原始作者为阿里巴巴集团 / FunASR / SenseVoice 团队。权重遵守 [FunASR Model Open Source License Agreement v1.1](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)，要求标注来源、作者并保留模型名称；模型转换与部署由 sherpa-onnx 提供。

## 启动

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。选择中文或英文，点击 **Start Recording**，授权麦克风，再点击 **Stop Recording** 提交该段音频；也可直接上传音频。页面显示文本、音频时长和处理耗时，提供复制按钮。普通模式直到停止录音才提交完整识别。

选择 **实时识别** 模式可在讲话过程中查看分段预览：停顿约 0.6 秒或连续采集约 4 秒后触发一段识别，实际出字还需等待本地推理。停止后处理尾段，并对整段音频再识别一次以校正最终文字，预览可能调整。这是题目 F6 允许的短分片近实时识别。文件上传始终走普通识别。

支持 WAV、Chrome/Edge 的 WebM/Opus（`.webm` 和 `.weba`），附加支持 OGG/Opus/Vorbis。最大上传大小 10 MiB；录音 60 秒自动停止，服务端音频最多 65 秒（按解码时长），超限拒绝而非静默截断。65 秒上传限制是本项目约定，不是原题要求。

## 规定接口

| Method | URL | 说明 |
| --- | --- | --- |
| GET | `/health` | HTTP 200 `{"status":"ok"}` |
| GET | `/` | 前端页面 |
| POST | `/api/transcribe` | multipart 字段 `file`、`language` (`zh` / `en`) |
| WebSocket | `/api/realtime` | 附加实时通道，16 kHz 单声道 PCM16；协议见设计文档 |

成功响应字段：`text`、`language`、`duration_seconds`、`processing_seconds`。4xx 用于参数/文件/时长错误；503 用于本地模型不可用；500 用于推理失败。`/health` 仅代表服务响应正常，不强制加载模型。

## 测试

常规自动化测试（Mock 与音频解码测试，不需要麦克风，也不会下载模型）：

```powershell
python -m pytest -q
```

真实本地模型中英文测试（必须先初始化模型）：

```powershell
python -m pytest -q --run-real-model -m real_model -s
```

可在页面手动上传 `samples/chinese.wav`、`samples/english.wav`。人工参考文本见 `samples/reference.txt`，样本来源及权限说明见 [`samples/SOURCE.md`](samples/SOURCE.md)。这两段是系统合成语音，不能替代实际麦克风中英文验证。项目所有者已同意公开发布，但第三方语音输出再分发条款尚未独立核实，不能将所有者同意视为第三方授权证明。

手动验证还包括：中文和英文麦克风录音、拒绝权限时的页面反馈，以及**模型准备完成后真正断开外网**仍可识别。结果与未完成项记录在 `docs/test-report.md`。不要为了做验证未经同意修改操作系统网络设置。

## 常见问题

- **503 / 模型未准备好：**运行 `python -m scripts.download_model`，确认 `models/sensevoice-small-int8/` 下有模型及 tokens。
- **麦克风权限被拒绝：**在 Chrome/Edge 地址栏重新授权；仍可改用上传文件。
- **有录音时长但识别为空：**检查 Chrome/Edge 网站麦克风设置中的实际输入设备，选择 `Microphone Array` 或所用物理麦克风，不要选择只采集电脑播放声音的“立体声混音”。浏览器选择可能不同于 Windows 默认输入。观察页面音量条，停止后回放录音确认讲话清楚。
- **不支持的文件或无法解码：**重新导出 WAV PCM 或浏览器录音 WebM/Opus；文件扩展名与内部编码都必须正确。
- **首次识别较慢：**模型首次加载和音频解码需要时间，后续请求复用对应语言的识别器。
- **断网测试：**确认两个语言的模型推理已成功后，手动断开外网并再次识别；全部静态资源均由本机提供。

## 文档

- `docs/execution-plan.md`：执行计划、范围及验收清单。
- `docs/requirements.md`：需求与边界。
- `docs/design.md`：架构、音频处理、模型选型。
- `docs/test-report.md`：实际测试和待人工验证项目。
- `docs/ai-development.md`：OpenCode 开发过程。

普通识别及实时加分功能均已实现。自动化、真实模型测试已通过，用户已确认实时中英文及中英文样本上传均正常，功能开发与核心使用验收结束。普通模式 60 秒自动停止和断网识别已有确认；未单独验证的实时边界及提交收尾见测试报告。
