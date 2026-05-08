# Virtual Mentor

## Share Memory L1 Store

`share_mem/` is the canonical L1 memory store for new work. The multi-agent L1
implementation now lives under `share_mem/l1/`; `long_term/` now keeps the
active recall surface and reserved L2 view entrypoints. Rebuild the Grace L1
store with:

```bash
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --clean
```

The old temporal `long_term/tree.json`, snapshots, and summarize/build-tree
pipeline are archived under `long_term/archive/legacy_temporal_l2_l3/`; new
short-term and long-term views should use `share_mem/tree.json` as their L1
source.

The first topic-tree implementation is a sidecar view, not a replacement for
raw L1. Build it after `share_mem/tree.json` exists:

```bash
uv run share_mem/build_topic_view.py --tree share_mem/tree.json --mode hybrid --model gemini-2.5-pro
```

This writes append-only per-meeting updates under `share_mem/topic_updates/`
and replays them into `share_mem/topic_tree.json` plus
`share_mem/topic_index.json`.

L1 type v2 is currently only a side-by-side experiment. Keep canonical
`share_mem/` untouched and write experiments to a separate root:

```bash
uv run share_mem/build_tree.py --output-root share_mem_experiments/type_v2_legacy_<timestamp> --taxonomy v2-memory-roles --include-legacy-type --transcript-dir meeting_recording/transcript/grace --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --clean
uv run share_mem/compare_l1_runs.py --baseline share_mem/tree.json --candidate share_mem_experiments/type_v2_legacy_<timestamp>/tree.json --out share_mem_experiments/type_v2_legacy_<timestamp>/comparison
```


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
- 長期記憶（時間記憶樹）：[`long_term/README.md`](long_term/README.md)，常用入口：`uv run long_term/cli.py --help`；目前 active surface 是 recall / L2 view，舊 full / incremental pipeline 已移到 `long_term/archive/legacy_temporal_l2_l3/`
- 會議錄音與轉錄流程：[`meeting_recording/README.md`](meeting_recording/README.md)

## Meeting Recording（摘要）

`meeting_recording/` 現在提供本地化逐字稿流程：

- `WhisperX` 先做 speaker diarization
- `Ollama` 再把 `SPEAKER_xx` 轉成 `老師 / 學生一 / 學生二`

使用方式見 [`meeting_recording/README.md`](meeting_recording/README.md)。
