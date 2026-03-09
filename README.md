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
```

## 使用方式

執行主程式：
```bash
uv run app/main.py
```

與 Virtual Mentor 對話，輸入 `exit`, `quit` 或 `q` 結束。

對話記錄會自動儲存在 `record/` 資料夾。

## Meeting Recording

`meeting_recording/` 現在提供本地化逐字稿流程：

- `WhisperX` 先做 speaker diarization
- `Ollama` 再把 `SPEAKER_xx` 轉成 `老師 / 學生一 / 學生二`

使用方式見 [meeting_recording/README.md](/d:/Documents/code/virtual-mentor/meeting_recording/README.md)。
