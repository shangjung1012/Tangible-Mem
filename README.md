# Virtual Mentor


## 安裝

1. Clone 專案
```bash
git clone https://github.com/shangjung1012/virtual-mentor.git
cd virtual-mentor
```

2. 安裝依賴（使用 uv）
```bash
uv sync
```

3. 設定環境變數

建立 `.env` 檔案並填入你的 API Key：
```
GEMINI_API_KEY=your_api_key_here
# optional: 要輪流使用多把 Gemini key 時，改用這行
GEMINI_API_KEYS=key_1,key_2,key_3
# optional: 預設生成模型（bridge / summarize / planner / gate）
GEMINI_MODEL=gemini-2.5-pro
# optional: 長期記憶 semantic retrieval 使用的 embedding 模型
GEMINI_EMBED_MODEL=models/gemini-embedding-001
```

## 使用方式

執行主程式：
```bash
uv run app/main.py
```

與 Virtual Mentor 對話，輸入 `exit`, `quit` 或 `q` 結束。

對話記錄會自動儲存在 `record/` 資料夾。

## 子模組說明

- 短期記憶：[`short_term/README.md`](short_term/README.md)
- 長期記憶（時間記憶樹）：[`long_term/README.md`](long_term/README.md)，常用入口：`uv run long_term/cli.py --help`；目前 L1 研究主線是 multi-agent bridge，full / incremental 保留作 baseline
- 會議錄音與轉錄流程：[`meeting_recording/README.md`](meeting_recording/README.md)

## Meeting Recording（摘要）

`meeting_recording/` 現在提供本地化逐字稿流程：

- `WhisperX` 先做 speaker diarization
- `Ollama` 再把 `SPEAKER_xx` 轉成 `老師 / 學生一 / 學生二`

使用方式見 [`meeting_recording/README.md`](meeting_recording/README.md)。
