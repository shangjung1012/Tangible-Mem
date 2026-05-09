# Meeting Recording Pipeline

這個流程使用 `WhisperX` 做中文轉錄 + speaker diarization，輸出 `meeting_recording/transcript/*.txt`。

## 需求

- Docker Desktop
- NVIDIA GPU + 可用的 Docker GPU runtime
- Hugging Face token（WhisperX diarization 需要）

## 環境變數

先建立 `meeting_recording/.env`：

```env
HF_TOKEN=your_huggingface_token
AUDIO_TARGET=grace
WHISPER_LANGUAGE=zh # zh, en
WHISPER_BATCH_SIZE=4
```

## 執行

在 [`meeting_recording/docker-compose.yml`](docker-compose.yml) 所在目錄執行：

```powershell
docker compose run --rm whisperx
```

或直接執行 [`run.ps1`](run.ps1)。

## 輸出

- `meeting_recording/transcript/*.txt`
  原始 diarization 逐字稿，格式像 `[SPEAKER_01]: ...`

