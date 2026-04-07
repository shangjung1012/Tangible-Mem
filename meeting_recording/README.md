# Meeting Recording Pipeline

這個流程現在分成兩段：

1. `WhisperX` 做中文轉錄 + speaker diarization，輸出 `meeting_recording/transcript/*.txt`
2. `role_map.py` 用本地 `Ollama` 模型把 `SPEAKER_xx` 映射成 `老師 / 學生一 / 學生二`

## 需求

- Docker Desktop
- NVIDIA GPU + 可用的 Docker GPU runtime
- Hugging Face token（WhisperX diarization 需要）

## 環境變數

先建立 `meeting_recording/.env`：

```env
HF_TOKEN=your_huggingface_token
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_PULL=1
```

## 執行

在 [`meeting_recording/docker-compose.yml`](docker-compose.yml) 所在目錄執行：

```powershell
docker compose run --rm whisperx
docker compose up --abort-on-container-exit role_map
```

第一行只做 WhisperX 轉錄。
第二行才做 Ollama 角色映射。

或直接執行 [`run.ps1`](run.ps1)。

## 輸出

- `meeting_recording/transcript/*.txt`
  原始 diarization 逐字稿，格式像 `[SPEAKER_01]: ...`
- `meeting_recording/transcript_role/*.txt`
  角色重標後逐字稿，格式像 `[老師]: ...`、`[學生一]: ...`
- `meeting_recording/transcript_role/*.mapping.json`
  每個 speaker 的對應關係、信心分數、使用的判斷方式

## 判斷方式

- 直接整理逐字稿中的實際對話片段
- 交給本地 Ollama 模型根據互動內容判斷誰是老師
- 如果 Ollama 沒起來、模型不存在、或輸出格式錯誤，流程會直接報錯停止

## 限制

- `學生一 / 學生二` 目前是「單一會議內」的標號，不保證跨會議是同一個人
- 如果 diarization 把同一位老師切成多個 `SPEAKER_xx`，本流程會嘗試把多個 speaker 合併成老師
- 如果音檔本身分軌很差，角色映射還是會受前面 diarization 品質影響
