# TAICHI Demo Handoff Guide

這份文件是給 partner / demo operator 用的最短交付說明。目標是讓對方 pull
repo 之後，可以確認自己正在展示正確的 ICSI optimization-v2 demo，而不是誤用
Grace canonical runtime 或舊實驗輸出。

## 1. Demo 定位

這個 demo 展示的是 **Memory Observatory**：

1. 會議逐字稿被整理成可追溯的 L1 evidence objects。
2. L1 evidence 被組織成 L2 topic context 與 L3 topic-family navigation。
3. 使用者問問題時，系統先找 L1，再帶出 L2/L3 脈絡。
4. 使用者可以檢查 trace、topic、evidence，並透過 sidecar feedback 做非破壞式修正。

重要邊界：

- ICSI demo 使用 optimization-v2 sidecar artifacts。
- Demo 不會修改 canonical `share_mem/`、`long_term/l2`、`long_term/l3`。
- Demo 可以說明系統如何被 inspect / steer，但不能宣稱已完成正式 user study。
- Demo 可以說 ICSI retrieval diagnostic 中 layered memory 找到更多 expected evidence than RAG。
- Demo 不能宣稱 generated answer quality 已全面贏過 RAG / full context。

## 2. 啟動方式

在 repo root 執行：

```powershell
uv run uvicorn memory_observatory.main:app --reload
```

打開：

```text
http://localhost:8000/#demo
```

常用頁面：

- `/#demo`: 70 秒 demo story，預設展示 ICSI。
- `/#trace`: Retrieval Trace，可看完整 formatted prompt context。
- `/#topics`: Topic Observatory，可看 L3 -> child L2 / L2。
- `/#explorer`: Memory Explorer，可檢查 L1 evidence object。
- `/static/presentation.html`: 截圖用的 controlled presentation page。

## 3. Pre-demo Health Check

每次 demo 前先跑：

```powershell
uv run python memory_observatory/demo_health_check.py --dataset icsi
```

目前 paper/demo artifact 預期：

- `status`: `pass`
- `resolved_backend`: `optimization_v2_artifact`
- trace 應該包含 L1 evidence、L2 topic context、L3 navigation、formatted prompt。

也可以用 API 檢查：

```text
GET /api/demo/health?dataset=icsi
```

如果 health check 是 `fail`，不要 live demo，先檢查 artifact path 是否存在。
如果是 `warn`，只有在 warning 是非關鍵 L3 navigation 時才可以展示，並在講稿中保守說明。

## 4. Current ICSI Artifact Roots

Memory Observatory 的 ICSI demo 讀以下 read-only sidecar artifacts：

| Layer | Path |
|---|---|
| L1 effective share memory | `optimization/reports/icsi_bmr_full_completed29_eval_pack_20260614/source_share_mem` |
| L2/L3 optimization runtime | `optimization/runs/icsi_bmr_full_completed29_v2_20260614/runtime` |
| Retrieval/system comparison | `optimization/reports/icsi_bmr_full_completed29_system_comparison_revised_20260614` |

這些 artifact 是 demo/paper 的穩定輸入。不要把 raw ICSI `share_mem` 當成
effective L1；ICSI 要優先使用 filtered/effective sidecar view。

## 5. 建議 70 秒 Demo Flow

| Time | Page | 內容 |
|---:|---|---|
| 0-10s | Demo Story | 指出 health panel：ICSI、optimization-v2 artifact、trace ready。 |
| 10-25s | Demo Story / Topic strip | 說明不是把 transcript 整包塞給模型，而是先變成 L1 evidence，再形成 topic context。 |
| 25-45s | Retrieval Trace | 展示 formatted prompt context：L1 Evidence Seeds -> L2 / Child-L2 Evolution Context -> L3 navigation。 |
| 45-60s | Topic Observatory | 展示 topic family 和 child topics，強調 L3 是 navigation，不是 standalone evidence。 |
| 60-70s | Memory Explorer / Feedback | 展示 object detail 或 sidecar feedback，強調修正不覆蓋 raw evidence。 |

## 6. 推薦 Demo Query

ICSI demo story 使用固定查詢，避免 live demo 變動：

```text
What evidence explains recurring audio and transcription problems in the ICSI meetings?
```

講法：

- 系統先選出相關 L1 evidence。
- 再把這些 L1 所屬的 L2 topic context 帶進 prompt。
- L3 只提供低解析度 topic map，幫助 reviewer 理解上下游脈絡。
- formatted prompt context 是真正會交給模型的內容，trace 可以被檢查。

## 7. 可以寫進論文的保守 Claims

可以說：

- The system makes memory retrieval inspectable through evidence-first traces.
- The interface separates evidence, topic context, and navigation context.
- Sidecar feedback supports non-destructive human correction.
- In the ICSI diagnostic, optimization-v2 layered retrieval improves expected evidence recall over lexical RAG while using far less context than full-context evidence injection.

不要說：

- optimization v2 has replaced canonical runtime defaults.
- L2/L3 hierarchy is always correct.
- Users improved memory quality through feedback in a completed user study.
- Generated answers are conclusively better than RAG or full context.

## 8. Partner Pull 後的快速檢查

```powershell
git pull
uv run python memory_observatory/demo_health_check.py --dataset icsi
uv run python -m unittest tests.test_memory_observatory_demo_health tests.test_memory_observatory_static_ui
```

如果 partner 要跑 chat app runtime，而不是 Observatory demo，必須另外確認
`LONG_TERM_BACKEND` 和 `OPTIMIZATION_V2_RUN_ROOT`。Observatory 的 ICSI dataset
switch 不等於整個 app runtime 已經切到 optimization v2。

