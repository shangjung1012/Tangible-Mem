# RETRIEVE 實作計畫（v2）

## 背景

本計畫針對 `long_term/` 的 recall 系統進行升級，將目前的 **keyword-based retrieval**（`_keyword_score()`）
替換為規格書（四、RETRIEVE）所描述的 **semantic-only retrieval** 流程：

```
Query → Embed → Cosine similarity (all L1) → Combined score → Top-k
     → LLM Gate (keep/discard) → Parent chain expansion (L2/L3)
     → Hierarchical prompt assembly
```

### 現況

| 元件 | 現況 |
|---|---|
| `recall.py::_keyword_score()` | 關鍵字比對（命中率），用於 L1/L2/short_term 搜尋 |
| `recall.py::search_l1()` | 對所有 L1 物件做 keyword scoring，回傳 score > 0 者 |
| `recall.py::search_l2()` | 對 L2 phase 做 keyword scoring |
| `recall.py::recall_gate()` | LLM 過濾，candidates > 3 時觸發 |
| `recall.py::recall()` | 主編排器，依 plan.keywords 驅動搜尋 |
| `recall.py::format_recall_for_prompt()` | L3 → L1 → short_term 排列 |
| `recall_planner.py` | LLM 分類 simple/complex，輸出 keywords + search_targets |

### 目標架構

- **L1 搜尋**：query embedding vs. 所有 L1 物件 embedding，取 top-k（不依賴 keywords）
- **L2/L3**：不直接語意搜尋，改由 parent chain expansion（從 L1 結果沿 phase_id 向上補）
- **Recall Gate**：現有 LLM 過濾邏輯保留，prompt 加入更多候選物件資訊（含時間與階段）
- **短期記憶**：維持 keyword-based（不在本次改動範圍）

---

## 受影響的檔案

| 檔案 | 動作 | 說明 |
|---|---|---|
| `long_term/embedder.py` | **新增** | Embedding 計算 + 持久化 cache |
| `long_term/recall.py` | **大幅修改** | 語意搜尋、combined scoring、parent chain、格式 |
| `long_term/schema.py` | **修改** | 新增常數、新增 L1 類型、更新 schema |
| `long_term/bridge.py` | **小幅修改** | 新增 `--meeting-date` 參數，寫入 `meeting_date` 欄位 |
| `long_term/build_tree.py` | **小幅修改** | 傳遞 `meeting_date` 給 bridge |
| `long_term/recall_planner.py` | **不動** | keywords 仍輸出供 short_term 使用 |
| `long_term/test_long_term.py` | **小幅修改** | 更新 `recall()` 呼叫，傳入 `embed_cache` |

---

## Step 1：新增 `long_term/embedder.py`

### 職責
- 提供 `embed_text()` 單次 embedding（含 cache 查詢）
- 提供 `cosine_similarity()` 向量相似度
- `EmbedCache`：讀/寫 `.embedding_cache.json`，以 SHA-256（前 16 hex）為 key

### Cache key 策略
Cache key = `SHA-256(text)[:16]`，**只依賴文字內容**，與 obj_id 無關。
好處：同一文字在不同 obj_id 出現時，只計算一次 embedding。
缺點：若 obj 的文字被修改，cache key 也會變（自動失效，會重新計算）。

### 完整程式碼

```python
"""embedder.py — Embedding computation and persistent caching.

Uses Google text-embedding-004 via the Gemini API.
Cache is stored at long_term/.embedding_cache.json.

Cache key strategy:
  key = SHA-256(text)[:16]  — content-addressed; if text changes, old entry
  is automatically abandoned and a new entry is computed on next recall.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from google import genai

EMBED_MODEL = "models/text-embedding-004"
DEFAULT_CACHE_PATH = Path(__file__).parent / ".embedding_cache.json"


def _text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class EmbedCache:
    """Persistent embedding cache backed by a JSON file."""

    def __init__(self, path: Path = DEFAULT_CACHE_PATH) -> None:
        self.path = path
        self._data: dict[str, list[float]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self) -> None:
        """Flush to disk (only if there are new entries)."""
        if not self._dirty:
            return
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False),
            encoding="utf-8",
        )
        self._dirty = False

    def get(self, text: str) -> list[float] | None:
        return self._data.get(_text_key(text))

    def set(self, text: str, embedding: list[float]) -> None:
        self._data[_text_key(text)] = embedding
        self._dirty = True


def embed_text(
    text: str,
    api_key: str,
    cache: EmbedCache,
    model: str = EMBED_MODEL,
) -> list[float]:
    """Return the embedding for *text*, using cache if available.

    Raises RuntimeError if the API call fails.
    """
    cached = cache.get(text)
    if cached is not None:
        return cached

    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(model=model, contents=text)
    emb: list[float] = result.embeddings[0].values  # type: ignore[index]
    cache.set(text, emb)
    return emb


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
```

### 注意事項
- `save()` 只在 `_dirty` 時寫入磁碟，避免無謂 I/O
- `EmbedCache` 需在呼叫結束後由 caller 呼叫 `cache.save()`
- `embed_text()` 呼叫 `client.models.embed_content()`，確認 `google-genai >= 0.8.0`

### Embedding 生命週期規則

| 時機 | 說明 |
|---|---|
| **何時產生** | 首次 recall 時 lazy 計算，非 STORE 時預先批次計算 |
| **何時失效** | 物件文字（content / evidence / related_topics）更新後，cache key 自然改變，下次 recall 自動重算 |
| **何時手動清除** | 若大量修改 L1 內容，可直接刪除 `.embedding_cache.json`，下次 recall 重建 |
| **cache 責任** | `.embedding_cache.json` 只是加速工具，`tree.json` 才是 source of truth |
| **summarize 後新節點** | L2/L3 不做 embedding，不需處理 |

---

## Step 2：修改 `long_term/schema.py`

### 2-1 新增常數

在 `DEFAULT_MODEL_NAME` 後面加入：

```python
EMBED_MODEL_NAME = "models/text-embedding-004"
```

### 2-2 擴充 L1 物件類型（必補）

```python
# 現有
MEMORY_OBJ_TYPES = {"decision", "todo", "method_change", "result"}

# 更新為
MEMORY_OBJ_TYPES = {
    "decision",       # 會議中做出的決策或結論
    "todo",           # 被指派或提及的待辦事項
    "method_change",  # 方法論、演算法、流程的變更（因果鏈核心）
    "result",         # 實驗結果、發現、觀察報告
    "open_question",  # 尚未解決的研究問題（保存不確定性與討論方向）
    "argument",       # 決策背後的論點與推理（「為什麼這樣做」的依據）
}
```

**新增類型的意義：**
- `open_question`：保留研究過程中的未解問題，讓系統能回答「當時還在爭議什麼」
- `argument`：保存決策的論點，而非只記錄結果，支援「為什麼做這個決定」的追溯

### 2-3 更新 `BRIDGE_RESPONSE_SCHEMA`

在 `type` 欄位的 `enum` 和 `description` 中加入新類型：

```python
"type": {
    "type": "string",
    "enum": sorted(MEMORY_OBJ_TYPES),  # 自動包含新類型
    "description": (
        "decision=決議, todo=待辦, "
        "method_change=方法變更, result=實驗結果或發現, "
        "open_question=尚未解決的研究問題, argument=決策背後的論點與推理"
    ),
},
```

### 2-4 L2 / L3 Schema Contract（必備欄位）

為避免 `format_recall_for_prompt()` 和 `expand_parent_chain()` 遇到缺欄位崩潰，
明確定義各層的必備欄位及 fallback 行為：

**L2 Phase（`phases[]` 陣列中的每個元素）必備欄位：**

| 欄位 | 型態 | Fallback 若缺失 |
|---|---|---|
| `phase_id` | `str` | 顯示 `"?"` |
| `time_range.start` | `str` | 顯示 `"?"` |
| `time_range.end` | `str` | 顯示 `"?"` |
| `summary` | `str` | 顯示空字串，不崩潰 |
| `key_decisions` | `list[str]` | 顯示空列表，不崩潰 |
| `child_meeting_ids` | `list[str]` | 視為空，parent chain expansion 跳過 |

**L3 Project Profile（`project_profile` 物件）必備欄位：**

| 欄位 | 型態 | Fallback 若缺失 |
|---|---|---|
| `methodology` | `str` | 跳過，不顯示 |
| `method_timeline` | `list[dict]` | 顯示空列表，不崩潰 |
| `core_values` | `list[str]` | 選填，跳過 |

`get_l3_profile()` 現有邏輯：若 `methodology` 與 `method_timeline` 均為空，回傳 `None`，
`format_recall_for_prompt()` 會直接跳過 L3 區塊。此行為保留不變。

---

## Step 3：新增 `meeting_date` 欄位（解決 timestamp 品質問題）

### 問題說明

`tree.json` 中 meeting 的 `timestamp` 欄位是 `bridge.py` 執行時的 UTC 時間，
**不是實際會議日期**。若所有 meeting 都在同一天批次建立，recency 分數會幾乎相等，
時間衰減失效。

### 解決方案

在 meeting node 新增獨立的 `meeting_date` 欄位，儲存實際會議日期（ISO 格式）。
`timestamp` 保留為系統寫入時間（buildtime），不用於 recency 計算。

### 3-1 Schema 異動（`schema.py`）

更新 `DEFAULT_TREE` 中 meeting 節點的範例結構，加入 `meeting_date` 欄位說明（comment 即可，不影響程式邏輯）。

### 3-2 `bridge.py` 異動

在 `insert_meeting_into_tree()` 中，新增 `meeting_date` 參數並寫入：

```python
def insert_meeting_into_tree(
    tree: dict[str, Any],
    meeting_id: str,
    source_file: str,
    timestamp: str,           # 系統寫入時間，保留不變
    memory_objects: list[dict[str, Any]],
    meeting_date: str = "",   # 新增：實際會議日期（YYYY-MM-DD 或 ISO 字串）
) -> None:
    meeting_node = {
        "meeting_id": meeting_id,
        "timestamp": timestamp,       # buildtime，不用於 recency
        "meeting_date": meeting_date, # 實際會議日期，用於 recency
        "source_file": source_file,
        "phase_id": "",
        "memory_objects": memory_objects,
    }
    # ... 其餘邏輯不變
```

在 CLI 的 `argparse` 中新增：

```python
parser.add_argument(
    "--meeting-date",
    default="",
    help="實際會議日期（YYYY-MM-DD），用於 recency 計算。若不傳則留空。",
)
```

### 3-3 `build_tree.py` 異動

若逐字稿檔名或 metadata 含有日期資訊，可在此解析後傳入 `meeting_date`。
目前若無法自動取得，留空字串即可（recency 自動 fallback 至 0.5）。

### 3-4 `recall.py` 中 `_recency_score()` 的 fallback 邏輯

`_recency_score()` 使用 `meeting_date`，若為空則 fallback 至 `timestamp`，若仍無法解析則回傳 `0.5`：

```python
def _recency_score(
    meeting_date: str,      # 優先使用，來自 meeting["meeting_date"]
    timestamp: str,         # fallback，來自 meeting["timestamp"]
    obj_type: str,
    query_date: datetime,
    importance: float,
) -> float:
    """Type-specific recency decay.

    Decay periods (spec):
      decision / method_change → 360 days, floor 0.3
      result                   → 180 days, floor 0 (0.3 if importance >= 0.8)
      todo                     → 30 days,  floor 0 (0.3 if importance >= 0.8)
      open_question            → 180 days, floor 0 (0.3 if importance >= 0.8)
      argument                 → 360 days, floor 0.3  (論點有長期參考價值)

    importance 使用 0.0–1.0 scale。>= 0.8 ≈ 規格書「>= 4/5」的高重要性。
    """
    # 優先使用 meeting_date，其次 timestamp，最後 fallback
    date_str = meeting_date if meeting_date else timestamp
    try:
        meeting_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.5  # graceful fallback

    delta_days = max(0, (query_date - meeting_dt).days)
    high_imp = importance >= 0.8

    if obj_type in ("decision", "method_change", "argument"):
        return max(0.3, 1.0 - delta_days / 360)
    elif obj_type in ("result", "open_question"):
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 180)
    elif obj_type == "todo":
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 30)
    else:
        floor = 0.3 if high_imp else 0.0
        return max(floor, 1.0 - delta_days / 180)
```

---

## Step 4：大幅修改 `long_term/recall.py`

### 4-1 `_keyword_score()` 去留（統一說明）

**`_keyword_score()` 保留，不刪除。**

原因：long-term L1/L2 改用 semantic embedding，但 **short-term retrieval 仍依賴 keyword matching**。
`_keyword_score()` 只從 long-term 的搜尋路徑中移除依賴，函式本身繼續存在供 short_term 使用。

改動：
- `search_l1()` → 刪除（改由 `search_l1_semantic()` 取代）
- `search_l2()` → 刪除（L2 改由 parent chain expansion 提供）
- `_keyword_score()` → **保留**，繼續在 `recall()` 的 short_term 分支中使用

### 4-2 保留不動的部分
- `_keyword_score()`：保留
- `get_l3_profile()`：保留
- `_extract_json()`：保留（gate 仍需要）
- `recall_gate()` 函式邏輯：保留，但 `_build_gate_prompt()` 更新（見 4-6）

### 4-3 刪除的部分
- `search_l1()`：整個函式刪除
- `search_l2()`：整個函式刪除

### 4-4 Import 更新

在現有 import 區塊頂端加入：

```python
from datetime import datetime, timezone

from embedder import EmbedCache, cosine_similarity, embed_text
```

### 4-5 新增輔助函式

#### Importance score

```python
def _importance_score(importance: float) -> float:
    """Map importance (0.0–1.0) to [0.0, 1.0] with clamping.

    Existing data uses 0.0–1.0 scale.
    Spec defines 1–5 → [0.2, 0.4, 0.6, 0.8, 1.0]; our scale is equivalent.
    """
    return max(0.0, min(1.0, float(importance)))
```

#### Combined score

```python
def _combined_score(
    s_sem: float,
    s_recency: float,
    s_importance: float,
    w_s: float = 0.6,
    w_r: float = 0.2,
    w_i: float = 0.2,
) -> float:
    """Weighted combination (spec §四 Step 4).

    Baseline weights: semantic=0.6, recency=0.2, importance=0.2.
    See §「權重調參計畫」for tuning guidance.
    """
    return w_s * s_sem + w_r * s_recency + w_i * s_importance
```

### 4-6 重寫 `search_l1()` → `search_l1_semantic()`

**舊函式**（`search_l1`）完整刪除，替換為：

```python
def search_l1_semantic(
    tree: dict[str, Any],
    query_emb: list[float],
    api_key: str,
    cache: EmbedCache,
    obj_types: list[str] | None = None,
    min_importance: float = 0.0,
    top_k: int = 30,
    query_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Search ALL L1 memory objects using semantic similarity + recency + importance.

    Embedding text strategy:
      text = content + " " + evidence + " " + " ".join(related_topics)

      Rationale: the embedding vector should capture the object's core content
      (content), the original supporting quote (evidence), and thematic context
      (related_topics). Embedding all three together yields richer semantic
      coverage than content alone, and avoids losing cross-meeting topic signals
      that related_topics carry.

    Steps (spec §四):
      1. Compute cosine similarity between query_emb and each L1 object embedding.
      2. Normalise cosine from [-1, 1] → [0, 1].
      3. Combine with recency and importance scores.
      4. Return top_k sorted by combined score (desc).
    """
    if query_date is None:
        query_date = datetime.now(timezone.utc)

    results: list[dict[str, Any]] = []

    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id", "")
        timestamp = meeting.get("timestamp", "")
        meeting_date = meeting.get("meeting_date", "")
        phase_id = meeting.get("phase_id", "")

        for obj in meeting.get("memory_objects", []):
            if obj_types and obj.get("type") not in obj_types:
                continue
            importance = float(obj.get("importance") or 0.0)
            if importance < min_importance:
                continue

            text = " ".join([
                obj.get("content", ""),
                obj.get("evidence", ""),
                " ".join(obj.get("related_topics", [])),
            ]).strip()
            if not text:
                continue

            obj_emb = embed_text(text, api_key, cache)

            cos = cosine_similarity(query_emb, obj_emb)
            s_sem = (cos + 1.0) / 2.0  # normalise [-1,1] → [0,1]

            s_recency = _recency_score(
                meeting_date, timestamp, obj.get("type", ""), query_date, importance
            )
            s_importance = _importance_score(importance)
            score = _combined_score(s_sem, s_recency, s_importance)

            results.append({
                "source": "long_term_l1",
                "meeting_id": meeting_id,
                "timestamp": timestamp,
                "meeting_date": meeting_date,
                "phase_id": phase_id,
                "obj_id": obj.get("obj_id", ""),
                "type": obj.get("type", ""),
                "content": obj.get("content", ""),
                "importance": importance,
                "evidence": obj.get("evidence", ""),
                "related_topics": obj.get("related_topics", []),
                "score": round(score, 4),
                "s_sem": round(s_sem, 4),
                "s_recency": round(s_recency, 4),
                "s_importance": round(s_importance, 4),
            })

    results.sort(key=lambda x: -x["score"])
    return results[:top_k]
```

### 4-7 新增 `expand_parent_chain()`

**關於 fallback 的效率說明：**
`_get_l2_for_meeting()` 的 fallback 是線性掃描所有 `child_meeting_ids`。
目前 phase 數量少（< 20），影響可忽略。
未來若 phase 數量顯著增加，可預先建立 `meeting_id → phase_id` 索引，
但此版本不實作（避免過早最佳化）。

```python
def _get_l2_for_meeting(tree: dict[str, Any], meeting_id: str) -> dict[str, Any] | None:
    """Find the L2 phase that lists *meeting_id* in child_meeting_ids.

    Note: linear scan; acceptable for current phase counts (< 20).
    Future optimization: pre-build meeting_id → phase_id index if needed.
    """
    for phase in tree.get("phases", []):
        if meeting_id in phase.get("child_meeting_ids", []):
            return phase
    return None


def expand_parent_chain(
    tree: dict[str, Any],
    l1_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Walk up the hierarchy for each kept L1 result.

    For each unique phase referenced by l1_results, fetch the L2 phase node.
    Also fetch the L3 project profile (singleton).
    Deduplicates: each phase_id appears at most once.

    Returns:
        l2_nodes   – list of unique L2 phase dicts (source='long_term_l2')
        l3_profile – L3 project profile dict, or None
    """
    seen_phase_ids: set[str] = set()
    l2_nodes: list[dict[str, Any]] = []

    for item in l1_results:
        phase_id = item.get("phase_id", "")
        meeting_id = item.get("meeting_id", "")

        phase = None
        if phase_id:
            if phase_id not in seen_phase_ids:
                phase = next(
                    (p for p in tree.get("phases", []) if p.get("phase_id") == phase_id),
                    None,
                )
        else:
            # fallback: scan child_meeting_ids (O(phases × meetings_per_phase))
            phase = _get_l2_for_meeting(tree, meeting_id)

        if phase:
            pid = phase.get("phase_id", "")
            if pid and pid not in seen_phase_ids:
                seen_phase_ids.add(pid)
                l2_nodes.append({"source": "long_term_l2", **phase})

    l3_profile = get_l3_profile(tree)
    return l2_nodes, l3_profile
```

### 4-8 更新 `_build_gate_prompt()`

加入 `timestamp`（或 `meeting_date`）與 `phase_id`，讓 LLM 能判斷哪些結果過時或屬於舊方案：

```python
def _build_gate_prompt(
    query: str,
    candidates: list[dict[str, Any]],
) -> str:
    candidates_text = ""
    for i, c in enumerate(candidates):
        obj_id = c.get("obj_id", c.get("phase_id", f"candidate_{i}"))
        content = c.get("content", c.get("summary", ""))
        obj_type = c.get("type", c.get("source", "?"))
        meeting_id = c.get("meeting_id", "")
        # 優先顯示 meeting_date，其次 timestamp
        date_str = c.get("meeting_date") or c.get("timestamp", "")[:10]
        phase_id = c.get("phase_id", "")
        importance = c.get("importance", "?")
        score = c.get("score", "?")
        candidates_text += (
            f"\n[{obj_id}] type={obj_type} meeting={meeting_id} "
            f"date={date_str} phase={phase_id} "
            f"importance={importance} score={score}\n"
            f"  {content}\n"
        )

    return f"""
你是「記憶過濾閘門」(Recall Gate)。
任務：從候選記憶物件中，篩選出與使用者問題真正相關的，剔除雜訊。

規則：
1) 回傳 JSON only。
2) relevant_obj_ids 列出相關物件的 ID（保留 5–8 個為佳）。
3) 只保留真正能回答問題或提供重要背景的物件。
4) 語意接近但實際不相關的，請剔除。
5) 高度重疊或重複的物件，只保留最具代表性的一筆。
6) 可根據 date / phase 資訊，剔除過時或已被推翻的物件。

使用者問題：
{query}

候選記憶物件：
{candidates_text.strip()}
""".strip()
```

### 4-9 更新主編排器 `recall()`

```python
def recall(
    query: str,
    plan: dict[str, Any],
    tree: dict[str, Any],
    api_key: str,
    model_name: str = DEFAULT_MODEL_NAME,
    short_term_memory: dict[str, Any] | None = None,
    query_date: datetime | None = None,
    embed_cache: EmbedCache | None = None,
    top_k_raw: int = 30,
) -> dict[str, Any]:
    """Execute a recall plan and return retrieved memories.

    Parameters
    ----------
    query : str
        The user's question.
    plan : dict
        Output of ``recall_planner.plan_recall()``.
    tree : dict
        The temporal memory tree (``tree.json``).
    api_key : str
        Gemini API key.
    model_name : str
        Gemini model name (for Recall Gate LLM calls).
    short_term_memory : dict | None
        The short-term memory (``current_memory.json``).
    query_date : datetime | None
        The date from which recency is calculated. Defaults to UTC now.
    embed_cache : EmbedCache | None
        Reusable embedding cache. If None, a fresh one is created (and saved).
    top_k_raw : int
        Number of top-scoring L1 candidates before LLM gate (default 30).

    Returns
    -------
    dict with keys:
        complexity, short_term_results, long_term_results (alias),
        long_term_l1, long_term_l2, project_profile
    """
    if query_date is None:
        query_date = datetime.now(timezone.utc)

    keywords = plan.get("keywords", [])
    targets = set(plan.get("search_targets", []))
    own_cache = embed_cache is None

    if embed_cache is None:
        embed_cache = EmbedCache()

    stm_results: list[dict[str, Any]] = []
    l1_results: list[dict[str, Any]] = []
    l2_results: list[dict[str, Any]] = []
    l3_profile = None

    # ── Short-term: keyword-based（不改動）──
    if "short_term" in targets and short_term_memory:
        for mw in short_term_memory.get("meeting_window", []):
            text = " ".join([mw.get("summary", ""), " ".join(mw.get("key_points", []))])
            score = _keyword_score(text, keywords)
            if score > 0:
                stm_results.append({
                    "source": "short_term",
                    "meeting_id": mw.get("meeting_id", ""),
                    "summary": mw.get("summary", ""),
                    "key_points": mw.get("key_points", []),
                    "score": score,
                })
        for ai in short_term_memory.get("action_items", []):
            text = f"{ai.get('title', '')} {ai.get('detail', '')}"
            score = _keyword_score(text, keywords)
            if score > 0:
                stm_results.append({
                    "source": "short_term",
                    "obj_id": ai.get("item_id", ""),
                    "type": "action_item",
                    "content": f"{ai.get('title', '')}: {ai.get('detail', '')}",
                    "status": ai.get("status", ""),
                    "score": score,
                })

    # ── Long-term: semantic search ──
    if any(t.startswith("long_term") for t in targets):
        # Step 2: encode full query as single embedding
        query_emb = embed_text(query, api_key, embed_cache)

        # Steps 3–5: semantic + recency + importance → top_k_raw candidates
        l1_candidates = search_l1_semantic(
            tree=tree,
            query_emb=query_emb,
            api_key=api_key,
            cache=embed_cache,
            top_k=top_k_raw,
            query_date=query_date,
        )

        # Step 6: LLM gate (keep/discard)
        if plan.get("complexity") == "complex" and len(l1_candidates) > 5:
            l1_results = recall_gate(query, l1_candidates, api_key, model_name)
        else:
            l1_results = l1_candidates

        # Step 7: parent chain expansion → L2 + L3
        l2_results, l3_profile = expand_parent_chain(tree, l1_results)

    # Flush cache to disk if we own it
    if own_cache:
        embed_cache.save()

    return {
        "complexity": plan.get("complexity", "simple"),
        "short_term_results": stm_results,
        "long_term_results": l1_results,   # backward compat alias
        "long_term_l1": l1_results,
        "long_term_l2": l2_results,
        "project_profile": l3_profile,
    }
```

### 4-10 更新 `format_recall_for_prompt()`

依規格書 Step 8 組裝順序：**L3 → L2 → L1 → short_term**：

```python
def format_recall_for_prompt(recall_result: dict[str, Any]) -> str:
    """Format recall results into text for injecting into a system prompt.

    Output order: L3 (project theme) → L2 (phase context) → L1 (memory objects)
    → short-term (if any).

    Fallback: if any required field is missing, output is skipped gracefully.
    """
    parts: list[str] = []

    # ── L3: Project Theme ──
    profile = recall_result.get("project_profile")
    if profile:
        parts.append("=== 研究計畫輪廓 (L3) ===")
        if profile.get("methodology"):
            parts.append(f"方法論：{profile['methodology']}")
        for entry in profile.get("method_timeline", []):
            parts.append(
                f"  [{entry.get('period', '?')}] {entry.get('method', '')} "
                f"→ {entry.get('status', '')}（{entry.get('reason', '')}）"
            )

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
                parts.append(phase["summary"])
            if phase.get("key_decisions"):
                parts.append("  關鍵決策：")
                for kd in phase["key_decisions"]:
                    parts.append(f"    · {kd}")

    # ── L1: Retrieved Memory Objects ──
    l1 = recall_result.get("long_term_l1", recall_result.get("long_term_results", []))
    if l1:
        parts.append("\n=== 記憶物件 (L1) ===")
        # Sort by meeting_date > timestamp > meeting_id for causal coherence
        def _sort_key(x: dict[str, Any]) -> str:
            return x.get("meeting_date") or x.get("timestamp") or x.get("meeting_id", "")
        for item in sorted(l1, key=_sort_key):
            date_str = item.get("meeting_date") or item.get("timestamp", "")[:10]
            parts.append(
                f"  [{item.get('meeting_id', '?')} | {date_str}] "
                f"({item.get('type', '?')}) "
                f"importance={item.get('importance', '?')} "
                f"score={item.get('score', '?')}\n"
                f"    {item.get('content', '')}"
            )

    # ── Short-term ──
    stm = recall_result.get("short_term_results", [])
    if stm:
        parts.append("\n=== 短期記憶結果 ===")
        for item in stm:
            if item.get("type") == "action_item":
                parts.append(
                    f"  [TODO] {item.get('content', '')} "
                    f"(status={item.get('status', '')})"
                )
            else:
                parts.append(
                    f"  [{item.get('meeting_id', '?')}] "
                    f"{item.get('summary', '')}"
                )

    return "\n".join(parts) if parts else "（無相關記憶）"
```

---

## Step 5：更新 `long_term/test_long_term.py`

在 `main()` 的 Step 2（測試 recall）建立 shared cache：

```python
# 在 test_questions loop 之前加入
from embedder import EmbedCache
shared_cache = EmbedCache()

# recall() 呼叫改為
result = recall(
    query=question,
    plan=plan,
    tree=tree,
    api_key=api_key,
    embed_cache=shared_cache,   # 新增
)

# loop 結束後
shared_cache.save()
```

---

## Step 6：確認依賴

無需新增套件（`google-genai` 已存在，`math` / `hashlib` 是標準庫）。
確認 `google-genai >= 0.8.0`（支援 `embed_content`）。

---

## 權重調參計畫

初始版本採用 spec 建議的 baseline：

```
w_semantic   = 0.6
w_recency    = 0.2
w_importance = 0.2
```

### 調參步驟

1. **建立 benchmark query set**（見下節）
2. 對每組 query，觀察 top-30 raw candidates 與 gate 後的結果
3. 若 recency 過度壓制語意相近但較早的重要物件，提高 `w_s` 或降低 `w_r`
4. 若結果偏向返回最近的低語意相關物件，提高 `w_s`
5. 調整後重跑 benchmark，比對 Precision@5（gate 後結果是否包含預期物件）

---

## Retrieval 品質評估計畫

### Benchmark Query Set

針對現有 `tree.json`（Bmr001–Bmr031）設計以下問題，並預先標注預期召回的 meeting_id 與 obj_id：

| 問題 | 預期類型 | 預期包含 |
|---|---|---|
| 「錄音增益問題的處理過程是什麼？」 | complex, method_change | Bmr001-xxx, Bmr002-xxx |
| 「多麥克風降噪的技術方向如何演進？」 | complex, method_change | 多個 Bmr |
| 「目前有哪些待辦事項尚未解決？」 | simple, todo | 最近幾場 Bmr |
| 「自製放大器問題的始末為何？」 | complex, decision + result | 相關 Bmr |

### 評估指標

- **Precision@5**：gate 後前 5 個結果中，預期物件的比例
- **Recall@10**：前 10 個結果中，預期物件是否全部出現
- **Gate 過濾率**：top-30 → gate 後剩餘數量（目標 5–8）

### 比較基準

對同一批問題，同時跑：
1. 新的 semantic-only retrieval（本計劃）
2. 舊的 keyword retrieval（目前 `search_l1()`）

比較 Precision@5，若 semantic 版本顯著改善，確認改動方向正確。

---

## 邊界條件與注意事項

### A. `phase_id` 為空時的 parent chain
目前 meeting 的 `phase_id` 在 `summarize.py phase` 執行後才填入。
若 phases 陣列為空，`expand_parent_chain()` 回傳空 list，不崩潰。
這是預期行為。

### B. Importance scale
現有資料使用 `0.0–1.0`，規格書 Recency 公式寫的是「`importance >= 4`」（1-5 制）。
換算：`>= 0.8` 視同高重要性，recency floor 拉至 0.3。
`BRIDGE_RESPONSE_SCHEMA` 定義 `0.0–1.0`，不需改動。

### C. `meeting_date` 為空的 fallback
若 `meeting_date` 為空（舊有 meeting 尚未補欄位），`_recency_score()` 自動 fallback 至 `timestamp`。
若 `timestamp` 也無法解析，回傳 `0.5`（讓 semantic similarity 主導排序）。
舊有 meeting 不需要重新跑 bridge，可逐步補欄位。

### D. 新 L1 類型的向下相容
`open_question` 和 `argument` 為新增類型。
舊有 `tree.json` 不含這兩種類型，沒有任何問題（搜尋時只是不會命中）。
新 bridge 處理的 meeting 才會開始產出這些類型。

### E. Recall Gate 觸發條件
`complexity == "complex" and len(l1_candidates) > 5` 時觸發。
若 candidates <= 5，直接全部保留，不呼叫 LLM gate（節省 API 用量）。

### F. Backward compatibility
`recall()` 回傳 dict 仍含 `long_term_results` key（等同 `long_term_l1`），
確保現有下游程式碼不會 break。

---

## 執行測試

```bash
# 在 virtual-mentor/ 根目錄執行
uv run long_term/test_long_term.py
```

預期行為：
- Step 1（Bridge）：行為不變，L1 記憶物件正常寫入
- Step 2（Recall）：
  - 第一次執行：cache 為空，呼叫 `text-embedding-004` API（~310 次）
  - 之後執行：cache 命中，幾乎不需 API
  - `long_term_l1` 包含語意最相關的 L1 物件（含 `s_sem`/`s_recency`/`s_importance` 分項分數）
  - `long_term_l2` 包含對應 phase 摘要
  - `project_profile` 包含 L3（需先執行 `summarize.py profile`）

---

## 改動摘要

| 函式 / 元素 | 改動 |
|---|---|
| `_keyword_score()` | **保留**（short_term 仍用，long_term 不再呼叫） |
| `search_l1()` | **刪除**，替換為 `search_l1_semantic()` |
| `search_l2()` | **刪除**（L2 改由 parent chain 提供） |
| `get_l3_profile()` | **保留** |
| `_build_gate_prompt()` | **更新**（加入 date / phase_id / importance / score） |
| `recall_gate()` | **保留邏輯**，觸發條件不變 |
| `recall()` | **重寫**（embed_cache, query_date, top_k_raw 參數） |
| `expand_parent_chain()` | **新增** |
| `_get_l2_for_meeting()` | **新增**（輔助） |
| `format_recall_for_prompt()` | **重寫**（L3 → L2 → L1，含 date 排序） |
| `_recency_score()` | **新增**（含 meeting_date fallback，新類型 decay） |
| `_importance_score()` | **新增** |
| `_combined_score()` | **新增** |
| `MEMORY_OBJ_TYPES` | **擴充**（加入 open_question, argument） |
| `BRIDGE_RESPONSE_SCHEMA.type.enum` | **擴充**（自動同步） |
| `EMBED_MODEL_NAME` | **新增常數** |
| `insert_meeting_into_tree()` | **新增** `meeting_date` 參數 |
| `bridge.py CLI` | **新增** `--meeting-date` flag |
