# 发布前测试结果摘要

以下为项目发布准备期间实际执行的命令及结果摘录，不是截图或逐字会话导出，也不代表干净环境复现。

## 常规自动化

```text
.venv\Scripts\python.exe -m pytest -q
42 passed, 6 skipped, 1 warning in 1.74s
```

默认跳过 6 项真实模型测试；不使用物理麦克风、不下载模型。警告为第三方 Starlette 对 httpx TestClient 的弃用提醒。

用户也已独立在本机 CMD 执行相同入口，提供结果：

```text
42 passed, 6 skipped, 1 warning in 1.54s
```

## 真实本地模型

```text
.venv\Scripts\python.exe -m pytest -q --run-real-model -m real_model -s
6 passed, 42 deselected, 1 warning in 10.82s
```

真实模型覆盖中文 WAV、英文 WAV、约 33 秒长音频、浏览器编码 WebM，以及中英文实时停止前预览与停止后全文校正。英文样本存在 `Wecome` 拼写误差；不以非空输出冒充完美识别率。

本轮实时累计推理耗时：中文约 1.46 秒、英文约 1.28 秒，包含最终校正，不是首字延迟。完整测试说明见 `../test-report.md`。
