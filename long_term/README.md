# Long-term Memory（時間記憶樹）

Current L1 implementation note: canonical multi-agent L1 extraction code now
lives in `share_mem/l1/`. This directory keeps temporal L2/L3, recall, legacy
CLI entrypoints, and compatibility wrappers for older imports.

Topic-tree is currently implemented as a `share_mem` sidecar/view, not as a
replacement for this directory's temporal L2/L3 schema. Build it with
`uv run share_mem/build_topic_view.py --tree share_mem/tree.json --mode hybrid --model gemini-2.5-pro`.

L1 type v2 is also side-by-side only. Use an experiment output root and compare
against canonical `share_mem/tree.json` before considering promotion:

```bash
uv run share_mem/build_tree.py --output-root share_mem_experiments/type_v2_legacy_<timestamp> --taxonomy v2-memory-roles --include-legacy-type --transcript-dir meeting_recording/transcript/grace --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --clean
uv run share_mem/compare_l1_runs.py --baseline share_mem/tree.json --candidate share_mem_experiments/type_v2_legacy_<timestamp>/tree.json --out share_mem_experiments/type_v2_legacy_<timestamp>/comparison
```

`long_term/` 是 Virtual Mentor 的跨會議記憶模組。它會把單場會議整理成 L1 記憶，再逐步彙整成 L2 phase 與 L3 project profile，供 recall 在回答問題時補上長期背景。

## 先看這裡

- 指令入口：`uv run long_term/cli.py --help`
- 主資料：`long_term/tree.json`
- 歷史快照：`long_term/snapshots/`
- 系統設計：`long_term/ARCHITECTURE.md`

最常用的幾個指令：

```bash
uv run long_term/cli.py bridge --transcript meeting_recording/transcript/grace/0422.txt --mode multi-agent
uv run long_term/cli.py build-tree --resume --phase-size 4
uv run long_term/cli.py rebuild-snapshots --dry-run
uv run long_term/cli.py smoke-todo
```

目前 L1 研究主線是 `--mode multi-agent`。`--mode full` 和 `--mode incremental`
仍保留作為 baseline/reference，不是主要開發路徑。

## 記憶層級

| 層級 | 內容 | 產生方式 |
| --- | --- | --- |
| `L1` | 單場會議的 `decision` / `todo` / `method_change` / `result` / `open_question` / `argument` | `bridge` |
| `L2` | 一個 phase 的 `summary` / `changes` / `open_to_next` | `summarize phase` |
| `L3` | 專案整體的 `core_goal` / `current_phase` / `established_methods` / `long_term_open_questions` | `summarize profile` |

Recall 目前走 semantic retrieval：先用 embedding 對 L1 做搜尋，再把 `semantic + recency + importance` 合成分數，必要時經過 Recall Gate，最後沿 parent chain 補回對應的 L2 / L3。

## 資料夾怎麼看

| 路徑 | 用途 |
| --- | --- |
| `cli.py` | long-term 專用 CLI 入口 |
| `bridge.py` | 單場 L1 bridge 入口；目前主線走 `--mode multi-agent` |
| `multi_agent_*.py` | multi-agent L1 pipeline、agents、validators、verifier、reducer |
| `summarize.py` | `L1 -> L2` 與 `L2 -> L3` 的彙整 |
| `recall.py` / `recall_planner.py` | recall 規劃、檢索、格式化 prompt |
| `build_tree.py` / `rebuild_snapshots.py` | 批次建樹與重建 snapshots |
| `gemini_incremental_extractor.py` / `incremental_store.py` | incremental function-calling baseline，目前保留作 reference |
| `scripts/` | smoke test / 評估腳本 |
| `tree.json` | 長期記憶主資料 |
| `snapshots/` | L2 / L3 snapshots 與評估輸出 |
| `docs/` | 設計稿與重構筆記 |
| `archive/` | 小型舊備份與 redesign preview，平常可忽略；大型生成快照不再放這裡 |

## 環境變數

在專案根目錄的 `.env` 至少放：

```env
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-gcp-project
GOOGLE_CLOUD_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/service-account.json
GEMINI_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=models/gemini-embedding-001
```

如果你走 Vertex AI express mode，也可以不用 service account，改放：

```env
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_API_KEY=your_vertex_api_key
GEMINI_MODEL=gemini-2.5-flash
```

如果你還是要走舊的 Gemini Developer API，才需要：

```env
GEMINI_API_KEY=your_api_key
# optional: 要輪流使用多把 key 時，改用這行
GEMINI_API_KEYS=key_1,key_2,key_3
# optional: 也可改用 GEMINI_API_KEY_1 / 2 / 3 寫法
```

## 常用流程

### 1. 單場 Bridge

預設是既有 full-transcript 模式：一次把整份逐字稿送給 Gemini，輸出 L1 記憶物件後寫回 `tree.json`。這條路徑保留作為研究 baseline；`--mode full` 與 `--mode monolithic` 等價。

```bash
uv run long_term/cli.py bridge \
  --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt
```

研究用 multi-agent L1 模式會把每個主要步驟都落成 JSON artifact，再把通過驗證的 L1 patch 寫回同一個 `tree.json` meeting node：

```bash
uv run long_term/cli.py bridge \
  --transcript meeting_recording/transcript/grace/0422.txt \
  --mode multi-agent \
  --research-log-dir long_term/research_logs
```

如果沒有明確傳 `--model`，bridge / summarize 會在載入 `.env` 後使用
`GEMINI_MODEL`，未設定時才退回 `gemini-2.5-flash`。

每次 run 會建立 `long_term/research_logs/<run_id>/`，至少包含：

- `run_meta.json`
- `graph_events.jsonl`
- `window_plans.json`
- `initial_segments.json`
- `boundary_refinement.json`
- `segments.json`
- `segment_coverage_validation.json`
- `segment_coarsening.json`
- `continuation_merges.json`
- `extraction_batches.json`
- `idea_units.json`
- `idea_unit_quality_validation.json`
- `previous_context_by_batch.json`（啟用 `--multi-agent-previous-context` 時）
- `raw_candidates.json`
- `batch_fallbacks.json`
- `grounded_candidates.json`
- `conflict_resolution.json`
- `verified_candidates.json`
- `rejected_candidates.json`
- `final_patch.json`
- `l1_quality_index.json`
- `viewpoint_recurrence.json`
- `metrics_summary.json`
- `status.json`
- `run_summary.json`
- `prior_context_pack.json`
- `cross_meeting_relations.json`
- `memory_activity_update.json`
- `final_meeting_node.json`
- `prompts/` 與 `responses/`

multi-agent 第一版完整實作 L1：`context_planner -> segmentation_agent -> segment repair/coarsening -> boundary_refinement -> idea_unit_agent -> idea_unit repair -> continuation_merge -> bounded l1_decision/todo/method_change/result/argument/open_question_agent -> evidence_grounding_agent -> cross_type_conflict_resolver -> verify_l1_candidates -> reduce_l1_patch -> persist_l1`。這裡的 multi-agent 是「多角色分工的 staged prompt pipeline」，不是每個 agent 都有獨立長期狀態或自治工具。boundary refinement 會修 `segments.json` 的語義邊界；continuation merge 則只決定下游 extraction batch，不改 segment，且過大的 batch 會依 idea-unit 上限再切小，避免 type agents 在太胖的 scope 裡只取前幾個候選。type agents 只吃單一 bounded extraction batch 的 idea units；candidate 會保留 `extraction_scope` 與 `segment_ids` 供追責。grounding acceptance 主要使用本地 evidence/content 對齊訊號；只有 near-threshold support 且 source unit 完整、evidence 存在、沒有 uncertainty note、confidence 足夠高時，才保留為 `near_threshold_grounding` 低權重候選。idea unit 的 `completeness` / `uncertainty_note` 會保留到 grounded / verified artifacts，並在 reducer 端保守降權，不直接作為 rejection reason。若 idea-unit validator 發現漏行、過胖或過碎，pipeline 會先呼叫 `idea_unit_repair_agent` 產生語義修補 units 或標記真正的 non-memory context；只有 repair 後仍不足時才使用 transcript-based fallback / deterministic compaction。`argument` 與 `open_question` 已接進同一個 bounded type-agent loop，但 reducer 會對這兩類使用較保守的 importance cap，避免把一般討論理由或暫時疑問灌得過高；`argument` 目前仍是獨立 L1 object，用來支援「為什麼這樣決定」的 recall，不是附著在 decision/method_change 的 rationale 欄位。`l1_quality_index.json` 會把 support score、source unit quality、quality warnings、evidence lines、source candidate IDs、viewpoint recurrence 等品質訊號寫成 sidecar；正式 `tree.json` 的 L1 schema 仍保持乾淨。非 dry-run multi-agent bridge 會把 run-level sidecar merge 到 `long_term/l1_quality_index.json`，後續 `summarize phase` 會讀這份 sidecar，讓 L2 摘要知道哪些 L1 是 strong / normal / tentative / weak；sidecar 會用 content/evidence hash 比對目前 L1，避免重跑同一 meeting 後舊 metadata 被誤用。`metrics_summary.json` 會記錄 semantic repair / deterministic fallback / compaction counts、LLM call count、stage latency 與粗略 text-token proxy；`status.json` / `run_summary.json` 會在 run 中持續更新，目前 stage、partial metrics 與錯誤資訊會在失敗或中斷時保留下來。L2/L3 不另建新 schema；multi-agent 寫入的 meeting node 與既有 `summarize phase` / `summarize profile` 相容。

`--multi-agent-previous-context` 是實驗性開關：typed L1 agents 會收到前 2 個 extraction batches 的少量 compact candidate summaries，僅用來理解代名詞、延續關係與避免重複；這些 summaries 尚未經過 grounding / reducer，因此 previous context 不可作為 evidence，也不應因為前文提到某 topic 就增加候選數。程式端仍限制 `source_unit_ids` 只能來自 current batch。每次 run 會寫 `previous_context_by_batch.json`，metrics 會記錄 context 是否啟用、哪些 batch 有 items、以及每 batch item 數。

cross-meeting interaction 目前採 sidecar 設計：bridge 會先建立 `prior_context_pack.json`，把少量相關舊 L1 / L3 方法放進 prompt 作為 disambiguation context，並明確要求不可把舊記憶當作新 evidence。非 dry-run multi-agent 寫入後會更新 `memory_relations_index.json`（continues / resolves / supersedes / reactivates 等關係）與 `memory_activity_index.json`（activation / state / touch_count），讓 `summarize phase` 和 recall 能用「品質、活躍度、跨會議關係」做保守加權；canonical `importance` 和 L1 schema 不會被改動。relations 會先用 viewpoint / concept key、related topics、lexical similarity 篩候選，再判斷 relation type；sidecar 會記錄 source/target content/evidence hash，避免重跑後 stale relation 被 prompt 或 recall 誤用。recall 可沿 relation graph 補少量 linked L1 context，但只作為 soft expansion，不取代原本 semantic search。

常見補充參數：

```bash
uv run long_term/cli.py bridge \
  --transcript ICSI_original_transcripts/transcripts/Bmr001.mrt \
  --tree long_term/tree.json \
  --snapshot-dir long_term/snapshots \
  --model gemini-2.5-flash \
  --timestamp 2000-06-14T17:00:00Z \
  --meeting-date 2000-06-14
```

也可以改用 incremental Gemini function-calling 模式。這個模式會先把逐字稿切成 SQLite 工作表中的逐行資料，讓 Gemini 透過 `read_transcript` 逐段讀取、更新 issue table、建立 raw L1 candidates；接著在寫入正式 L1 前先做一層輕量 candidate review，最後仍回到既有 normalizer 與 `tree.json` 輸出流程。

```bash
uv run long_term/cli.py bridge \
  --transcript meeting_recording/transcript/grace/16.txt \
  --mode incremental \
  --incremental-db long_term/incremental_bridge.db \
  --dataset-profile grace
```

補充：

- `--mode full` / `--mode monolithic` 是 baseline，保留原本 full-transcript bridge 行為。
- `--mode multi-agent` 需要可用的 GenAI 認證，會額外輸出可逐步檢查與評估的 research logs。可用 `--multi-agent-window-size`、`--multi-agent-lookback-lines`、`--multi-agent-lookahead-lines` 控制 context planner 的 deterministic window。
- `--mode incremental` 需要可用的 GenAI 認證。支援 Vertex AI（`GOOGLE_GENAI_USE_VERTEXAI=true`，搭配 `GOOGLE_CLOUD_PROJECT` + `GOOGLE_APPLICATION_CREDENTIALS`，或 `GOOGLE_API_KEY`）以及舊的 Gemini API key。若是多把 API key 模式，會自動輪替使用。
- `--dataset-profile auto` 會從 transcript 路徑推斷 preset；目前內建：
  - `isci`：保留目前 ISCI/ICSI 逐字稿的穩定設定（`chunk_size=40`, `issue_episode_gap_lines=15`）
  - `grace`：針對較長的中文 turn-level transcript 使用較窄的掃描設定（`chunk_size=24`, `issue_episode_gap_lines=10`）
  - 也可用 `--chunk-size` 或 `--issue-episode-gap-lines` 手動覆寫
- incremental 會把進度印到 stderr，例如目前 round、掃到第幾行、issues / raw L1 數量；`--max-tool-rounds 0` 代表依逐字稿長度自動估算上限。長會議會定期從 SQLite 工作狀態重建 Gemini context，避免 input token 歷史持續膨脹。
- Gemini client 預設會使用 `500s` HTTP timeout；若想在 Vertex / Gemini API 上更保守或更寬鬆，可用 `GEMINI_HTTP_TIMEOUT_S` 覆寫。
- `--incremental-db` 是工作日誌，不是 canonical long-term store；正式輸出仍是 `long_term/tree.json` 和 snapshots。
- incremental 的 raw L1 candidate 不是直接進 `tree.json`：會先做一層 deterministic review，包含近似重複候選合併、同 issue checklist fragment 合併、缺少 evidence 的 speculative object 降權或丟棄、以及 linked issue 語意對齊的小幅加減分。這一層只作用在 incremental working objects，不改 final L1 schema。
- `update_issue` 會優先記錄 `forward_scan` 的代表性 evidence 行，而不是把長段落的每一行都塞進 `issue_mentions`；`create_l1_object` 會優先使用 `update_issue` 回傳的 exact `issue_id`，若模型只傳 `issue_key` 也會在儲存時解析成 canonical issue。
- `importance` 會經過共用校準：L1 物件依 evidence / related topics / 高影響語意微調；incremental issues 會先用 `issue_key` / 相似 title-summary 合併同一議題，再用 `episode_count`（相隔超過 15 行才算再次出現）設定最低合理分數，避免連續幾行 evidence 灌高重要性。若 raw L1 object 連到高 importance issue，會在進入 normalizer 前得到最多 `+0.08` 的小幅 bonus；final `tree.json` 的 L1 schema 不變。

### 2. 手動建立 L2 / L3

```bash
uv run long_term/cli.py summarize phase \
  --phase-id P-007 \
  --time-start Bmr027 \
  --time-end Bmr030 \
  --meetings Bmr027 Bmr028 Bmr029 Bmr030
```

如果 `tree.json` 同層有 `l1_quality_index.json`，`summarize phase` 會自動在 prompt 裡加入 compact quality tag。`strong/normal` 的 L1 較容易升級成 phase-level change；`tentative/weak` 只作背景或被保守處理；沒有 sidecar 的 legacy L1 會標為 `quality=unknown`，仍按原本 type / importance / content / evidence 判斷。

```bash
uv run long_term/cli.py summarize profile
```

### 3. 批次建立整棵樹

```bash
uv run long_term/cli.py build-tree --resume --phase-size 4
```

補充：

- `--dry-run` 只看會處理哪些會議
- `--no-auto-summarize` 只建 L1，不自動補 L2 / L3
- `--meetings Bmr001:Bmr005 Bmr009` 可只跑指定範圍
- `--model` 可指定批次 L1/L2/L3 使用的 Gemini model；未指定時會讀取 `.env` 的 `GEMINI_MODEL`，再退回預設 `gemini-2.5-flash`

### 4. 用既有 `tree.json` 重建 snapshots

```bash
uv run long_term/cli.py rebuild-snapshots --dry-run
uv run long_term/cli.py rebuild-snapshots --phase-size 4
```

這個流程不會重打 L1 bridge，只會根據現有 `tree.json` 重跑 L2 / L3。

### 5. 驗證與評估

本地單元測試，不打 API：

```bash
uv run python -m unittest discover -s tests
```

打 API 的 smoke check：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/cli.py smoke-todo
```

評估 prompt injection：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run long_term/cli.py eval-injection \
  --question "錄音增益問題的處理過程是什麼？" \
  --show-only
```

## 需要更細節時

- 系統設計與資料流：`long_term/ARCHITECTURE.md`
- multi-agent L1 詳解：`long_term/docs/MULTI_AGENT_L1_ARCHITECTURE.md`
- retrieve redesign 筆記：`long_term/docs/RETRIEVE_IMPLEMENTATION_PLAN.md`
- L2 / L3 redesign 筆記：`long_term/docs/L2_L3_REDESIGN_PLAN.md`

如果只是要開始跑 long-term，優先記住 `uv run long_term/cli.py --help` 就夠了。

## Current L1 Source

New L1 memory work uses `share_mem/tree.json` as the canonical store. Rebuild it
from the Grace transcripts with:

```bash
uv run share_mem/build_tree.py --transcript-dir meeting_recording/transcript/grace --mode multi-agent --dataset-profile grace --model gemini-2.5-pro --clean
```

This command always uses the `share_mem/l1` multi-agent L1 pipeline. The older
`long_term/tree.json` temporal tree remains useful as a legacy L2/L3 reference,
but new L1 recall should read from `share_mem/tree.json`.
