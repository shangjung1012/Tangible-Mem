# Virtual Mentor

Virtual Mentor is a meeting-memory QA agent. The current memory architecture is:

```text
short_term current context
share_mem canonical L1 evidence
long_term generated L2/L3 topic context
app memory router
```

`share_mem/` is the canonical L1 memory store. The multi-agent L1
implementation lives under `share_mem/l1/`; `long_term/` owns generated L2/L3
topic sidecars and recall. The old temporal `long_term/tree.json`, snapshots,
and summarize/build-tree pipeline are archived under
`long_term/archive/legacy_temporal_l2_l3/`.

Canonical architecture docs:

- Memory flow: [`doc/l1_l2_update_retrieve_flow.md`](doc/l1_l2_update_retrieve_flow.md)
- Evaluation design: [`doc/evaluation_plan.md`](doc/evaluation_plan.md)
- L1 store: [`share_mem/README.md`](share_mem/README.md)
- Long-term L2/L3: [`long_term/README.md`](long_term/README.md)

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
GEMINI_EMBED_MODEL=text-embedding-004
```

## 使用方式

執行主程式：
```bash
uv run app/main.py
```

與 Virtual Mentor 對話，輸入 `exit`, `quit` 或 `q` 結束。

對話記錄會自動儲存在 `record/` 資料夾。

## Memory Commands

Build canonical L1:

```bash
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --output-root share_mem --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --taxonomy v2-memory-roles --include-legacy-type --clean
```

Build and validate L2:

```bash
uv run long_term/cli.py build-l2-view --share-mem-root share_mem --output-root long_term/l2 --mode deterministic --clean
uv run long_term/cli.py validate-l2-view --share-mem-root share_mem --root long_term/l2 --out long_term/l2/validation
uv run long_term/cli.py validate-l3-view --share-mem-root share_mem --l2-root long_term/l2 --l3-root long_term/l3 --out long_term/l3/validation
uv run python long_term/evaluate_retrieval.py --queries long_term/eval/long_term_retrieval_queries.jsonl --out long_term/eval --no-llm --retrieval-mode lexical
```

Update short-term memory from a share_mem snapshot:

```bash
uv run short_term/update_memory.py --snapshot <share_mem snapshot path>
```

## 子模組說明

- L1 store: `share_mem/`
- Long-term L2/L3 recall: `long_term/`
- Short-term current context: `short_term/`
- 會議錄音與轉錄流程：[`meeting_recording/README.md`](meeting_recording/README.md)

## Meeting Recording（摘要）

`meeting_recording/` 現在提供本地化逐字稿流程：

- `WhisperX` 先做 speaker diarization
- `Ollama` 再把 `SPEAKER_xx` 轉成 `老師 / 學生一 / 學生二`

使用方式見 [`meeting_recording/README.md`](meeting_recording/README.md)。
