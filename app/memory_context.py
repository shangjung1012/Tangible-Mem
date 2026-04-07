import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHORT_TERM_MEMORY_PATH = ROOT / "short_term" / "current_memory.json"
LONG_TERM_TREE_PATH = ROOT / "long_term" / "tree.json"
LONG_TERM_DIR = ROOT / "long_term"

if str(LONG_TERM_DIR) not in sys.path:
    sys.path.insert(0, str(LONG_TERM_DIR))

from recall import format_recall_for_prompt, recall
from recall_planner import plan_recall


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def retrieve_memory_context(
    query: str,
    api_key: str,
    model_name: str,
    max_context_chars: int = 4000,
) -> str:
    tree = load_json_object(LONG_TERM_TREE_PATH)
    short_term_memory = load_json_object(SHORT_TERM_MEMORY_PATH)

    if not tree and not short_term_memory:
        return "（無相關記憶）"

    plan = plan_recall(query=query, api_key=api_key, model_name=model_name)
    result = recall(
        query=query,
        plan=plan,
        tree=tree,
        api_key=api_key,
        model_name=model_name,
        short_term_memory=short_term_memory,
    )
    context = format_recall_for_prompt(result)
    if len(context) > max_context_chars:
        return context[:max_context_chars] + "\n...(truncated)"
    return context
