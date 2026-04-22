"""Quick smoke test for TODO recall behavior.

Checks:
1) planner outputs type_filter=['todo'] for TODO-like queries
2) long-term recall returns TODO-only items when type_filter is active
"""

from __future__ import annotations

from pathlib import Path

from embedder import EmbedCache
from io_utils import load_api_keys, load_tree
from recall import recall
from recall_planner import plan_recall


def main() -> None:
    api_key = load_api_keys()
    tree = load_tree(Path("long_term/tree.json"))

    if not tree.get("meetings"):
        raise RuntimeError("tree.json has no meetings. Run bridge first.")

    query = "目前有哪些待辦事項？"
    plan = plan_recall(query, api_key)

    print("=== Planner ===")
    print("query:", query)
    print("complexity:", plan.get("complexity"))
    print("targets:", plan.get("search_targets"))
    print("keywords:", plan.get("keywords"))
    print("type_filter:", plan.get("type_filter"))

    cache = EmbedCache()
    result = recall(
        query=query,
        plan=plan,
        tree=tree,
        api_key=api_key,
        embed_cache=cache,
    )
    cache.save()

    l1 = result.get("long_term_l1", [])
    todo_only = all(item.get("type") == "todo" for item in l1)

    print("\n=== Recall ===")
    print("long_term_l1_count:", len(l1))
    print("todo_only:", todo_only)

    for item in l1[:10]:
        print(
            f"- {item.get('obj_id', '?')} "
            f"type={item.get('type', '?')} "
            f"score={item.get('score', '?')} "
            f"content={str(item.get('content', ''))[:80]}"
        )

    expected_filter = plan.get("type_filter") == ["todo"]
    if not expected_filter:
        raise RuntimeError("Planner did not apply type_filter=['todo'] for TODO query.")
    if l1 and not todo_only:
        raise RuntimeError("Recall returned non-todo objects despite todo type_filter.")

    print("\nPASS: TODO planner filter + recall type filtering are working.")


if __name__ == "__main__":
    main()
