# L2 / L3 Schema 重設計計劃

## 問題確認

### 現況數據（以實際 snapshot 為基準）

| 指標 | 現況 |
|---|---|
| L3 `methodology` 字數 | ~2200 字（Bmr031.json）|
| L3 `method_timeline` 條目數 | 100+ 條 |
| L2 `method_evolution` 條目數（P-007）| 11 條，每條含 reason |
| L2 `key_decisions` 條目數（P-007）| 14 條 |
| L2 `unresolved_issues` 條目數（P-007）| 14 條 |
| L2 + L3 注入 prompt 的 token 量 | 1500+ tokens |

### 根本問題

- L3 ≈ L2 flatten，L2 ≈ L1 flatten，沒有真正的抽象層次
- `method_evolution.reason` 把 L1 `argument` 物件的內容複製到 L2
- `methodology` 是詳細的工程日誌，不是方法論概述
- `method_timeline` 屬於 L2 層的資訊，不應出現在 L3

---

## 目標 Schema

### 新 L2 Schema

```json
{
  "phase_id": "P-007",
  "time_range": {"start": "Bmr027", "end": "Bmr030"},
  "summary": "同意書流程完善、Transcriber 工具改進、語音辨識策略調整",
  "changes": [
    {"status": "adopted",   "method": "同意書：未回覆視為同意，截止 7/15"},
    {"status": "adopted",   "method": "Transcriber：截短檔案以避免演示載入過慢"},
    {"status": "adopted",   "method": "語音辨識訓練：改用男性專用數據集"},
    {"status": "abandoned", "method": "遞增音調蜂鳴聲方案"}
  ],
  "open_to_next": [
    "NSF ITR 預算需下週五前提交",
    "Transcriber 多波形顯示功能尚未實作"
  ],
  "child_meeting_ids": ["Bmr027", "Bmr028", "Bmr029", "Bmr030"]
}
```

**欄位說明：**

| 欄位 | 限制 | 用途 |
|---|---|---|
| `summary` | ≤ 2 句，≤ 60 字 | 本階段主軸 |
| `changes` | 最多 5 條，每條 `method` ≤ 30 字 | 本期淨方法變化 |
| `changes[].status` | `adopted` / `abandoned` / `evolved` | 變化方向 |
| `open_to_next` | 最多 2 條，每條 ≤ 40 字 | 留給下一階段的懸案 |
| `child_meeting_ids` | 保留（內部索引用）| 不進 prompt，供 parent chain 查詢 |

**廢除欄位：**

| 廢除欄位 | 原因 |
|---|---|
| `key_decisions` | 與 `changes` 語意重疊 |
| `method_evolution` | 改為 `changes`（移除 `reason`，限制 5 條）|
| `unresolved_issues` | 改為 `open_to_next`（限制 2 條）|

---

### 新 L3 Schema

```json
{
  "project_id": "virtual-mentor",
  "time_range": {"start": "Bmr001", "end": "Bmr031"},
  "core_goal": "建立高品質多人會議語音語料庫，支援語音辨識、轉錄與會議摘要研究",
  "current_phase": "錄音系統穩定化與轉錄流程建立",
  "established_methods": [
    "錄音：16kHz 降採樣，排除空閒頻道，全程開麥",
    "轉錄：自動分割 → 轉錄員精修 → IBM 處理",
    "數字朗讀：讀作單一數字，行間停頓",
    "麥克風：嘴角旁一個半拇指距離，頭戴式",
    "語音分割：多混合高斯模型，24 特徵集"
  ],
  "long_term_open_questions": [
    "語料庫格式標準化（LDC vs 自定義）尚未決定",
    "自製放大器 vs 採購方案的長期取捨"
  ],
  "child_phase_ids": ["P-001", "P-002", "P-003", "P-004", "P-005", "P-006", "P-007", "P-008"]
}
```

**欄位說明：**

| 欄位 | 限制 | 用途 |
|---|---|---|
| `core_goal` | ≤ 2 句，≤ 60 字 | 整個專案在做什麼 |
| `current_phase` | ≤ 1 句，≤ 30 字 | 目前所處大階段 |
| `established_methods` | 最多 5 條，每條 ≤ 35 字 | 目前確立的核心做法 |
| `long_term_open_questions` | 最多 3 條，每條 ≤ 40 字 | 長期懸而未決的問題 |
| `child_phase_ids` | 保留（內部索引用）| 不進 prompt，供 parent chain 查詢 |

**廢除欄位：**

| 廢除欄位 | 原因 |
|---|---|
| `methodology` | 內容等於 L1 flatten，字數過多，改為 `established_methods` 條列 |
| `method_timeline` | 屬於 L2 層資訊，L3 不應重複 |
| `core_values` | 對 recall 無實際幫助（如「效率」、「創新」等抽象原則）|

---

## Token 估算

| 場景 | 改前 | 改後 |
|---|---|---|
| L3 單獨 | ~700 tokens | ~80 tokens |
| L2 單個 phase | ~400 tokens | ~60 tokens |
| L1 + L2（1 phase）+ L3 注入 prompt | ~1800+ tokens | ~200-300 tokens |

---

## 受影響的檔案

| 檔案 | 動作 |
|---|---|
| `long_term/schema.py` | 更新 `PHASE_SUMMARY_SCHEMA`、`PROFILE_UPDATE_SCHEMA`、`DEFAULT_TREE` |
| `long_term/summarize.py` | 更新 prompt、更新 phase_node / profile 的欄位映射 |
| `long_term/recall.py` | 更新 `get_l3_profile()` gating、更新 `format_recall_for_prompt()` |
| `long_term/build_tree.py` | **不需修改**，但下次執行會自動產生新格式的 L2/L3（它內部呼叫 `summarize_phase()` 和 `update_project_profile()`，schema 改動後自動生效）|
| `long_term/rebuild_snapshots.py` | **不需修改**（理由同上，且已確認腳本存在，見「Step 4 說明」）|
| `long_term/tree.json` | 需重新跑 `rebuild_snapshots.py` 以重建 L2/L3 |
| `long_term/snapshots/` | 重建後自動更新 |

---

## Step 1：修改 `schema.py`

### 1-1 更新 `DEFAULT_TREE`

將 `project_profile` 的預設空樹改為新 schema：

```python
DEFAULT_TREE: dict[str, Any] = {
    "tree_version": 0,
    "last_updated_utc": "",
    "project_profile": {
        "project_id": "",
        "time_range": {"start": "", "end": ""},
        # 新欄位
        "core_goal": "",
        "current_phase": "",
        "established_methods": [],
        "long_term_open_questions": [],
        # 保留（內部索引用，不進 prompt）
        "child_phase_ids": [],
    },
    "phases": [],
    "meetings": [],
}
```

### 1-2 替換 `PHASE_SUMMARY_SCHEMA`

完整替換（舊 schema 整個刪除）：

```python
PHASE_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "本階段的主軸描述，限 1-2 句，60 字以內（繁體中文）。"
                "只寫這段期間發生了什麼主要事情，不要列舉細節。"
            ),
        },
        "changes": {
            "type": "array",
            "description": (
                "本階段的淨方法變化，最多 5 條。"
                "只寫跨越整個 phase 後的淨結果，不要每個小調整都列出。"
                "每條 method 限 30 字以內。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["adopted", "abandoned", "evolved"],
                        "description": "adopted=本期確立, abandoned=本期棄用, evolved=持續演進中",
                    },
                    "method": {
                        "type": "string",
                        "description": "方法變化的一句話描述，30 字以內，不含 reason。",
                    },
                },
                "required": ["status", "method"],
                "additionalProperties": False,
            },
            "maxItems": 5,
        },
        "open_to_next": {
            "type": "array",
            "description": (
                "本階段結束時仍懸而未決、需要下一階段處理的問題，最多 2 條，每條 40 字以內。"
                "不要把所有 todo 都列入，只保留真正影響下一步進展的懸案。"
            ),
            "items": {"type": "string"},
            "maxItems": 2,
        },
    },
    "required": ["summary", "changes", "open_to_next"],
    "additionalProperties": False,
}
```

### 1-3 替換 `PROFILE_UPDATE_SCHEMA`

完整替換（舊 schema 整個刪除）：

```python
PROFILE_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "core_goal": {
            "type": "string",
            "description": (
                "整個專案的核心目標，1-2 句，60 字以內（繁體中文）。"
                "回答「這個專案在做什麼、最終目的是什麼」，不要描述方法細節。"
            ),
        },
        "current_phase": {
            "type": "string",
            "description": (
                "目前整個研究所處的大階段，1 句，30 字以內。"
                "例如：「錄音系統穩定化與轉錄流程建立」。"
            ),
        },
        "established_methods": {
            "type": "array",
            "description": (
                "目前已確立並持續使用的核心做法，最多 5 條，每條 35 字以內。"
                "只列跨越多個 phase 都沒有變動的穩定做法，不要列每個 phase 的微調。"
                "已棄用的方法不要列入。"
            ),
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "long_term_open_questions": {
            "type": "array",
            "description": (
                "從多個 phase 看下來，至今仍懸而未決的長期問題，最多 3 條，每條 40 字以內。"
                "只保留真正橫跨多個階段、影響整個研究方向的問題，不要列近期的 todo。"
            ),
            "items": {"type": "string"},
            "maxItems": 3,
        },
    },
    "required": ["core_goal", "current_phase", "established_methods", "long_term_open_questions"],
    "additionalProperties": False,
}
```

---

## Step 2：修改 `summarize.py`

> **注意**：本 Step 涉及兩個完全不同的函式，分別負責不同層級，必須**分開替換**：
> - `_build_phase_summary_prompt()`：產生 **L2 Phase Summary** 的 LLM prompt（Step 2-1）
> - `_build_profile_update_prompt()`：產生 **L3 Project Profile** 的 LLM prompt（Step 2-3）
>
> 兩者位於 `summarize.py` 的不同區塊，請勿互相覆蓋。

### 2-1 替換 `_build_phase_summary_prompt()`（L2 prompt）

```python
def _build_phase_summary_prompt(
    phase_id: str,
    meetings: list[dict[str, Any]],
) -> str:
    meetings_text = ""
    for m in meetings:
        meetings_text += f"\n--- Meeting: {m['meeting_id']} ---\n"
        for obj in m.get("memory_objects", []):
            meetings_text += (
                f"  [{obj['type']}] (importance={obj['importance']}) "
                f"{obj['content']}\n"
            )

    return f"""
你是「長期記憶彙整器」。
任務：將多個會議的 L1 記憶物件彙整成一個階段性摘要（L2 Phase Summary）。

★ 核心原則：每一層只回答自己層次的問題，不要抄寫下層的細節。

欄位規則：
1) summary：本階段的主軸是什麼？1-2 句，60 字以內。只寫大方向，不要列舉。
2) changes：本階段「淨」的方法變化，最多 5 條。
   - 只寫這段期間確立或棄用的重要做法，不要把每個小調整都列出來
   - 每條 method 限 30 字以內，不要含 reason（reason 留在 L1）
   - status 只有三種：adopted（確立）/ abandoned（棄用）/ evolved（持續演進）
3) open_to_next：本階段結束時仍懸而未決的真正懸案，最多 2 條，每條 40 字以內。
   - 不要把所有 todo 都列入，只保留真正影響下一步進展的問題
4) 回傳 JSON only，文字使用繁體中文。

階段 ID：{phase_id}

本階段包含的會議記憶物件：
{meetings_text}
""".strip()
```

### 2-2 更新 `summarize_phase()` 的欄位映射

找到函式中建立 `phase_node` 的區塊，替換為：

```python
    # 舊：
    # phase_node: dict[str, Any] = {
    #     "phase_id": phase_id,
    #     "time_range": {"start": time_start, "end": time_end},
    #     "summary": result.get("summary", ""),
    #     "key_decisions": result.get("key_decisions", []),
    #     "method_evolution": result.get("method_evolution", []),
    #     "unresolved_issues": result.get("unresolved_issues", []),
    #     "child_meeting_ids": child_meeting_ids,
    # }

    # 新：
    phase_node: dict[str, Any] = {
        "phase_id": phase_id,
        "time_range": {"start": time_start, "end": time_end},
        "summary": result.get("summary", ""),
        "changes": result.get("changes", []),
        "open_to_next": result.get("open_to_next", []),
        "child_meeting_ids": child_meeting_ids,   # 保留供 parent chain 查詢
    }
```

同時移除 `main()` 中這行（舊欄位的 print）：

```python
# 刪除：
print(f"Method timeline entries: {len(profile['method_timeline'])}")

# 改為：
print(f"Established methods: {len(profile.get('established_methods', []))}")
print(f"Open questions: {len(profile.get('long_term_open_questions', []))}")
```

### 2-3 替換 `_build_profile_update_prompt()`（L3 prompt）

```python
def _build_profile_update_prompt(
    phases: list[dict[str, Any]],
    current_profile: dict[str, Any],
) -> str:
    phases_text = ""
    for p in phases:
        tr = p.get("time_range", {})
        phases_text += (
            f"\n--- Phase: {p['phase_id']} "
            f"({tr.get('start', '?')} ~ {tr.get('end', '?')}) ---\n"
        )
        phases_text += f"  Summary: {p.get('summary', '')}\n"
        for ch in p.get("changes", []):
            phases_text += f"  [{ch.get('status', '?')}] {ch.get('method', '')}\n"
        for issue in p.get("open_to_next", []):
            phases_text += f"  [open] {issue}\n"

    # 只傳遞精簡的 current profile（不包含 child_phase_ids 等索引欄位）
    slim_profile = {
        "core_goal": current_profile.get("core_goal", ""),
        "current_phase": current_profile.get("current_phase", ""),
        "established_methods": current_profile.get("established_methods", []),
        "long_term_open_questions": current_profile.get("long_term_open_questions", []),
    }
    current_profile_text = json.dumps(slim_profile, ensure_ascii=False, indent=2)

    return f"""
你是「研究計畫輪廓更新器」。
任務：根據所有階段摘要（L2）更新研究計畫的長期輪廓（L3 Project Profile）。

★ 核心原則：L3 回答的是「整個專案的全局」，不是彙整 L2 的細節。

欄位規則：
1) core_goal：整個專案的核心目標，1-2 句，60 字以內。不要描述方法細節。
2) current_phase：目前整個研究所處的大階段，1 句，30 字以內。
3) established_methods：目前跨越多個 phase 都沒有變動的穩定核心做法，最多 5 條，每條 35 字以內。
   - 只列已確立且仍在使用的做法，不要列已棄用的
   - 不要把某一個 phase 的單次決策列進來
4) long_term_open_questions：從多個 phase 看下來至今仍懸而未決的長期問題，最多 3 條，每條 40 字以內。
   - 只保留真正橫跨多個階段、影響整個研究方向的問題
   - 不要列近期的 todo 或已解決的問題
5) 回傳 JSON only，文字使用繁體中文。

目前的 Project Profile（供更新參考）：
{current_profile_text}

所有階段摘要（按時間順序）：
{phases_text}
""".strip()
```

### 2-4 更新 `update_project_profile()` 的欄位映射

找到函式中建立 `profile` dict 的區塊，替換為：

```python
    # 舊：
    # profile: dict[str, Any] = {
    #     "project_id": project_id,
    #     "time_range": {...},
    #     "methodology": result.get("methodology", ""),
    #     "core_values": result.get("core_values", []),
    #     "method_timeline": result.get("method_timeline", []),
    #     "child_phase_ids": sorted(p["phase_id"] for p in phases),
    # }

    # 新：
    profile: dict[str, Any] = {
        "project_id": project_id,
        "time_range": {
            "start": min(all_starts) if all_starts else "",
            "end": max(all_ends) if all_ends else "",
        },
        "core_goal": result.get("core_goal", ""),
        "current_phase": result.get("current_phase", ""),
        "established_methods": result.get("established_methods", []),
        "long_term_open_questions": result.get("long_term_open_questions", []),
        "child_phase_ids": sorted(p["phase_id"] for p in phases),  # 保留供索引用
    }
```

---

## Step 3：修改 `recall.py`

### 前置確認：`recall()` 回傳 key 對照

`format_recall_for_prompt()` 接收的 `recall_result` dict 由 `recall()` 產生。
根據 `RETRIEVE_IMPLEMENTATION_PLAN.md` 的新版 `recall()` 實作，回傳格式為：

```python
return {
    "complexity": ...,
    "short_term_results": stm_results,
    "long_term_results": l1_results,   # backward compat alias
    "long_term_l1": l1_results,
    "long_term_l2": l2_results,        # ← Step 3-2 的 L2 區塊讀取此 key
    "project_profile": l3_profile,     # ← Step 3-2 的 L3 區塊讀取此 key
}
```

因此 Step 3-2 的程式碼使用 `recall_result.get("long_term_l2", [])` 和
`recall_result.get("project_profile")` 是**正確的**，不需要修改 `recall()` 的回傳介面。

### 前置確認：`expand_parent_chain()` 的欄位相容性

`expand_parent_chain()` 的實作（見 `RETRIEVE_IMPLEMENTATION_PLAN.md`）：

```python
l2_nodes.append({"source": "long_term_l2", **phase})
```

它只是把 phase dict 展開後傳出，**不直接讀取 `key_decisions`、`method_evolution` 等舊欄位**。
讀取這些欄位的是 `format_recall_for_prompt()`，而那部分在 Step 3-2 中已一併更新。
因此 `expand_parent_chain()` 本身**不需要修改**。

### 3-1 更新 `get_l3_profile()`

舊的 gating 依賴已廢除的 `methodology` 欄位：

```python
# 舊：
def get_l3_profile(tree: dict[str, Any]) -> dict[str, Any] | None:
    profile = tree.get("project_profile", {})
    if not profile.get("methodology") and not profile.get("method_timeline"):
        return None
    return {"source": "long_term_l3", **profile}

# 新：
def get_l3_profile(tree: dict[str, Any]) -> dict[str, Any] | None:
    profile = tree.get("project_profile", {})
    if not profile.get("core_goal") and not profile.get("established_methods"):
        return None
    return {"source": "long_term_l3", **profile}
```

### 3-2 更新 `format_recall_for_prompt()` 的 L2 / L3 區塊

**L3 區塊**（找到「# ── L3: Project Theme ──」的區塊，整個替換）：

```python
    # ── L3: Project Theme ──
    profile = recall_result.get("project_profile")
    if profile:
        parts.append("=== 研究計畫輪廓 (L3) ===")
        if profile.get("core_goal"):
            parts.append(f"目標：{profile['core_goal']}")
        if profile.get("current_phase"):
            parts.append(f"目前階段：{profile['current_phase']}")
        if profile.get("established_methods"):
            parts.append("確立做法：")
            for m in profile["established_methods"]:
                parts.append(f"  · {m}")
        if profile.get("long_term_open_questions"):
            parts.append("長期懸案：")
            for q in profile["long_term_open_questions"]:
                parts.append(f"  ? {q}")
```

**L2 區塊**（找到「# ── L2: Phase / Monthly Context ──」的區塊，整個替換）：

```python
    # ── L2: Phase / Monthly Context ──
    l2 = recall_result.get("long_term_l2", [])
    if l2:
        parts.append("\n=== 階段摘要 (L2) ===")
        for phase in l2:
            phase_id = phase.get("phase_id", "?")
            tr = phase.get("time_range", {})
            time_str = f"{tr.get('start', '?')} ~ {tr.get('end', '?')}"
            parts.append(f"\n[Phase {phase_id} | {time_str}]")
            if phase.get("summary"):
                parts.append(f"  {phase['summary']}")
            for ch in phase.get("changes", []):
                status_label = {
                    "adopted": "✓確立",
                    "abandoned": "✗棄用",
                    "evolved": "→演進",
                }.get(ch.get("status", ""), ch.get("status", "?"))
                parts.append(f"  [{status_label}] {ch.get('method', '')}")
            for issue in phase.get("open_to_next", []):
                parts.append(f"  [懸案] {issue}")
```

---

## Step 4：重建 L2/L3 資料

### `rebuild_snapshots.py` 存在性確認

`rebuild_snapshots.py` 已存在於 `long_term/` 目錄（已確認）。其運作邏輯：

1. 讀取 `tree.json` 中的所有 L1 meetings（已排序）
2. 逐步模擬「每加入一場 meeting」的累積狀態
3. 對每個步驟：
   - 計算該 meeting 所屬 phase（`phase_index = (step-1) // phase_size`，預設 phase_size=4）
   - 呼叫 `summarize_phase()` 產生當前 phase 的累積 L2 摘要
   - 儲存 `snapshots/L2/P-XXX__BmrYYY.json`
   - 呼叫 `update_project_profile()` 從所有已累積 phases 更新 L3
   - 儲存 `snapshots/L3/BmrYYY.json`
4. 支援 `--resume`：跳過已存在的 snapshot，從中斷點續跑
5. 自動對 503 錯誤做指數退避重試（最多 3 次）
6. 最終將最後一個 step 的 L2/L3 狀態寫入 `tree.json`

**注意**：`rebuild_snapshots.py` 內部呼叫 `summarize_phase()` 和 `update_project_profile()`，
這兩個函式已在 Step 2 修改過 schema，**重建腳本本身不需要修改**。

### 執行步驟

```bash
# 在 virtual-mentor/ 根目錄執行

# 0. 先備份目前的 tree.json（重建前必做）
cp long_term/tree.json long_term/tree.json.bak

# 1. 先確認 dry-run 無誤（確認 31 場 meeting 都在範圍內）
uv run long_term/rebuild_snapshots.py --dry-run

# 2. 正式重建（約 62 次 LLM 呼叫：31 次 L2 + 31 次 L3）
uv run long_term/rebuild_snapshots.py
```

### Rollback 方案

若重建到一半失敗，或新格式的 recall 效果不如預期：

```bash
# 方案 A：從備份還原 tree.json（回到重建前的完整狀態）
cp long_term/tree.json.bak long_term/tree.json

# 方案 B：若只是中途失敗，用 --resume 從上次中斷的地方繼續
uv run long_term/rebuild_snapshots.py --resume
```

**注意：**
- `--resume` 會跳過已存在的 snapshot 檔案，但仍會把 L2 phase 讀入 running_tree 以保持 L3 的連續性
- 若 `rebuild_snapshots.py` 完全重跑後 L3 效果仍不符合期望，可調整 `_build_profile_update_prompt()` 的 prompt 文字後再次重建
- L1 資料（`meetings` 陣列）在整個過程中**不受影響**

---

## 改動摘要表

### `schema.py`

| 元素 | 動作 |
|---|---|
| `DEFAULT_TREE.project_profile` | 移除 `methodology`, `core_values`, `method_timeline`；新增 `core_goal`, `current_phase`, `established_methods`, `long_term_open_questions` |
| `PHASE_SUMMARY_SCHEMA` | 完整替換：移除 `key_decisions`, `method_evolution`, `unresolved_issues`；新增 `changes`, `open_to_next` |
| `PROFILE_UPDATE_SCHEMA` | 完整替換：移除 `methodology`, `core_values`, `method_timeline`；新增 `core_goal`, `current_phase`, `established_methods`, `long_term_open_questions` |

### `summarize.py`

| 函式 | 動作 |
|---|---|
| `_build_phase_summary_prompt()` | 完整替換（新規則：50字 summary，5條 changes，2條 open_to_next）|
| `summarize_phase()` | 更新 `phase_node` 欄位映射 |
| `_build_profile_update_prompt()` | 完整替換（精簡 current_profile 輸入，新規則）|
| `update_project_profile()` | 更新 `profile` 欄位映射，更新 print 輸出 |

### `recall.py`

| 函式 | 動作 |
|---|---|
| `get_l3_profile()` | 更新 gating：從 `methodology` 改為 `core_goal` |
| `format_recall_for_prompt()` | 更新 L2 區塊（`changes`, `open_to_next`）和 L3 區塊（`core_goal`, `current_phase`, `established_methods`, `long_term_open_questions`）|

---

## 邊界條件

### A. `child_meeting_ids` / `child_phase_ids` 保留不廢除

這兩個欄位從 **LLM prompt 輸入**和**格式化 prompt 輸出**中移除，但仍寫入 `tree.json` 和 snapshot。

- `child_meeting_ids`：`expand_parent_chain()` 的 fallback 路徑需要此欄位
  （當 meeting 的 `phase_id` 欄位為空時，用 `child_meeting_ids` 反查所屬 phase）
- `child_phase_ids`：`update_project_profile()` 的程式碼邏輯仍計算此欄位，保留供未來擴展

兩者均由程式碼寫入，不需要 LLM 輸出，因此不在 `PHASE_SUMMARY_SCHEMA` / `PROFILE_UPDATE_SCHEMA` 中定義。

### B. 現有 `tree.json` 的舊欄位清理

重建後，`rebuild_snapshots.py` 會用新的 `phase_node` dict **upsert** 進 `tree["phases"]`，
舊的 `key_decisions`、`method_evolution`、`unresolved_issues` 欄位會在 upsert 時消失。

如果發現重建後的 `tree.json` 還殘留舊欄位，代表某個 phase 的 upsert 未成功，
可手動清除後重跑：

```bash
# 緊急清除方式（注意：清除後需重跑完整重建，不能用 --resume）
python3 -c "
import json
with open('long_term/tree.json') as f: t = json.load(f)
t['phases'] = []
# 同時清除每個 meeting 的 phase_id 標記，讓重建重新填入
for m in t['meetings']: m['phase_id'] = ''
with open('long_term/tree.json', 'w') as f: json.dump(t, f, ensure_ascii=False, indent=2)
print('Cleared')
"
```

### C. `expand_parent_chain()` 欄位相容性（已確認）

`expand_parent_chain()` 的核心動作是 `l2_nodes.append({"source": "long_term_l2", **phase})`，
只展開整個 phase dict，**不直接讀取任何具名的 L2 欄位**。
讀取 `changes`、`open_to_next` 等欄位的是 `format_recall_for_prompt()`，已在 Step 3-2 更新。

以下是 `expand_parent_chain()` 唯一讀取的 L2 欄位，均不受本次改動影響：

| 欄位 | 用途 | 是否受影響 |
|---|---|---|
| `phase_id` | 去重用 | 否，欄位保留 |
| `child_meeting_ids` | fallback 查詢 | 否，欄位保留 |

### D. `build_tree.py` 自動相容

`build_tree.py` 在每處理完一批 meetings 後，會呼叫 `summarize_phase()` 和 `update_project_profile()`。
這兩個函式在 Step 2 修改後，`build_tree.py` 下次執行時會自動產生新格式的 L2/L3，無需額外修改。

---

## 預期改善

| 指標 | 改前 | 改後 |
|---|---|---|
| L3 字數 | ~2200 字 | ~150 字 |
| L3 token 量 | ~700 tokens | ~80 tokens |
| L2 字數（P-007）| ~1200 字 | ~120 字 |
| L2 token 量 | ~400 tokens | ~60 tokens |
| L2 + L3 注入 prompt | ~1500+ tokens | ~150 tokens |
| 是否有真正的層次抽象 | 否（L3 ≈ L2 flatten）| 是 |
