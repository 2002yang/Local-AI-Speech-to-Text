# OpenCode 关键开发过程记录

本文件是脱敏的工作过程摘要，用于定位实际证据；不是逐字会话导出。原始对话记录保留在本 OpenCode 会话，用户可按需要导出。以下补充了实时实现、最终测试及用户验收结果。

## 一、需求与技术设计

1. OpenCode 在浏览器打开腾讯文档《面试考核题-v1》，核对 F1–F5、F6、API、Windows 11 / Python 3.12 限制、自动化和手动验收要求。
2. 检查本机 Windows 11 x64、Python 3.12.10、i7-10750H、约 16 GB RAM 以及 Chrome/Edge、麦克风设备。
3. 比较 Qwen3-ASR ONNX、SenseVoiceSmall 与 faster-whisper；选 sherpa-onnx + SenseVoiceSmall ONNX INT8。用户确定项目内放模型、录音 60 秒、上传 65 秒、实时识别放后面。
4. 输出 `docs/execution-plan.md`、`docs/requirements.md`、`docs/design.md`；执行计划在 OpenCode Review 面板展示给用户。

## 二、功能开发与集成

1. 新建 `.venv`（Python 3.12），按 `requirements.txt` 成功安装预编译依赖。
2. 显式运行 `python -m scripts.download_model`，下载到当前项目的 `models/sensevoice-small-int8/`；模型 SHA-256 `c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51`。
3. 在 `app/audio.py` 实现 WAV / WebM / OGG 有界音频解码、16 kHz 单声道重采样和分段；`app/asr.py` 显式给模型传入 `zh` / `en`；`app/main.py` 实现原题三个 HTTP 接口；`static/` 实现录音/上传页面。
4. 在浏览器实际上传中文、英文 WAV，均在页面得到本地识别文字；通过 Chromium MediaRecorder 编码并上传英语 WebM/Opus，后端返回 HTTP 200 和英语文本。截图：`english-upload-result.jpeg`；浏览器录音格式夹具：`tests/fixtures/browser-recorded.webm`（来源是合成样本经浏览器重新编码，非麦克风实录）。

## 三、真实测试与问题修复

- `python -m pytest -q`：加入实时功能及 `.weba` 回归后 42 通过、6 项真实模型默认跳过，1 条第三方 TestClient 弃用警告。用户在本机 CMD 重新执行同一测试入口，反馈 `42 passed, 6 skipped, 1 warning in 1.54s`。
- `python -m pytest -q --run-real-model -m real_model -s`：真实模型测试 6 通过，含中文、英文、33 秒长段、实际浏览器 WebM 及实时中英文停止前出字/最终校正；英语输出的 “Wecome” 与参考文本存在一处拼写差异，已写入 `docs/test-report.md`。
- 发现纯音 WebM 返回 `。` 的非语音标点；OpenCode 在 `app/asr.py` 增加仅标点过滤，并补充单元测试，重启服务再次请求同类 WebM 得到 `text: ""`。
- 规定启动端口首次报 WinError 10013；查得 8000 被酷狗音乐占用，未自行终止用户进程；用户自行结束酷狗后规定启动命令运行成功，`GET /health` 返回 `{"status":"ok"}`。
- 内置浏览器测试权限拒绝时提示与按钮恢复。内置浏览器剪贴板权限也被拒绝，已加入自动选中文字、提示 Ctrl+C 的退路。未尝试绕过被拒绝的浏览器权限。

## 四、实时功能与上传修复

- 用户在普通功能可用后授权实现 F6。使用 AudioWorklet 将音频转成 16 kHz PCM16，经 WebSocket 送本地 CPU 模型，按停顿/约 4 秒更新预览，停止后处理尾段。
- 实测短分段存在断词和重复，调整低能量边界，并增加停止后一次完整音频识别校正全文；真实模型测试确认停止前出字，最终文本恢复完整上下文。
- 用户反馈 `.weba` 上传失败。检查为有效 WebM/Opus，定位为扩展名白名单遗漏；补充 `.weba` 支持且保留容器/编码校验。用户文件真实模型转写成功，并以已有合成夹具添加回归测试，没有把用户私人录音提交仓库。

## 用户验收及证据边界

- 用户确认普通真人中文/英文录音可识别、60 秒自动停止及无外网识别成功；随后确认真人实时中英文和项目中英文样本上传均正常。
- 上述为用户反馈，不伪造成代理实际操作或额外截图；实时模式 60 秒/断网等边界未单独逐项报告，具体见 `docs/test-report.md`。
- 现有页面截图为普通模式英文上传结果；未补造实时或测试截图。三阶段开发过程通过本记录及 `docs/ai-development.md` 说明，原始会话未整体公开。
- 用户明确授权发布 `2002yang` 账号下的公开仓库，并同意公开两份测试 WAV。音频来源及第三方许可核实边界见 `samples/SOURCE.md`。干净环境独立复现尚未执行。
- 已创建并推送公开仓库 https://github.com/2002yang/Local-AI-Speech-to-Text ，默认分支 `main`；GitHub API 核对公开状态和远端文件清单，确认两份 WAV、参考文本及开发证据在内，模型权重与环境目录未上传。提交作者使用 GitHub noreply 邮箱，不公开本机 Git 配置中的私人邮箱。
