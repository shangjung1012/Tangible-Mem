from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, load_json, utc_now_iso, write_json, write_text


TYPE_LIKE_LABELS = {
    "decision",
    "proposal",
    "argument",
    "finding",
    "action item",
    "open issue",
    "todo",
}
GENERIC_ONLY_LABELS = {
    "data",
    "system",
    "memory",
    "discussion",
    "topic",
    "thing",
    "process",
    "method",
    "issue",
    "meeting",
}
WEAK_TERMINAL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "with",
}
WEAK_START_WORDS = {
    "basically",
    "maybe",
    "probably",
    "actually",
    "just",
    "kind",
    "sort",
}
ARTIFACT_WORDS = {
    "uh",
    "um",
    "hmm",
    "okay",
    "yeah",
    "go",
    "ahead",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)


def _tokens(label: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(label or ""))]


def review_label(label: str, *, representative_l1_ids: list[str] | None = None) -> list[str]:
    text = " ".join(str(label or "").strip().lower().split())
    tokens = _tokens(text)
    reasons: list[str] = []
    if not text:
        reasons.append("empty_label")
        return reasons
    if text in TYPE_LIKE_LABELS:
        reasons.append("type_like_label")
    if text in GENERIC_ONLY_LABELS:
        reasons.append("generic_only_label")
    if len(tokens) == 1 and tokens[0] in ARTIFACT_WORDS | GENERIC_ONLY_LABELS:
        reasons.append("single_word_artifact_label")
    if tokens and tokens[-1] in WEAK_TERMINAL_WORDS:
        reasons.append("weak_terminal_word")
    if tokens and tokens[0] in WEAK_START_WORDS:
        reasons.append("weak_start_word")
    if len(tokens) >= 2 and all(token in ARTIFACT_WORDS for token in tokens):
        reasons.append("conversation_filler_label")
    if len(text) <= 4 and not text.isupper():
        reasons.append("ambiguous_short_label")
    if not representative_l1_ids:
        reasons.append("missing_representative_l1")
    return reasons


def _load_l2_nodes(run_root: Path) -> list[dict[str, Any]]:
    path = run_root / "l2" / "l2_view.json"
    if not path.exists():
        return []
    payload = load_json(path)
    return list(payload.get("l2_nodes", []) or payload.get("topics", []) or [])


def _load_child_nodes(run_root: Path) -> list[dict[str, Any]]:
    path = run_root / "l3" / "l3_view.json"
    if not path.exists():
        return []
    payload = load_json(path)
    children: list[dict[str, Any]] = []
    for parent in payload.get("l3_parents", []) or payload.get("parents", []) or []:
        parent_id = parent.get("l3_id") or parent.get("parent_l3_id")
        for child in parent.get("child_l2_nodes", []) or parent.get("children", []) or []:
            row = dict(child)
            row["parent_l3_id"] = parent_id
            children.append(row)
    return children


def _representative_ids(node: dict[str, Any]) -> list[str]:
    ids = node.get("representative_l1_ids") or node.get("linked_obj_ids") or node.get("obj_ids") or []
    if isinstance(ids, list):
        return [str(item) for item in ids if str(item)]
    return []


def _review_item(*, node: dict[str, Any], node_type: str, reason_codes: list[str]) -> dict[str, Any]:
    label = str(node.get("label") or "")
    representative = _representative_ids(node)
    item_id = str(node.get("l2_id") or node.get("child_l2_id") or node.get("source_l2_id") or label)
    return {
        "review_id": f"LP-{node_type}-{item_id}",
        "item_type": node_type,
        "l2_id": item_id if node_type == "l2_topic" else node.get("source_l2_id") or item_id,
        "child_l2_id": item_id if node_type == "child_l2_topic" else "",
        "parent_l3_id": str(node.get("parent_l3_id") or ""),
        "label": label,
        "reason_codes": reason_codes,
        "representative_l1_ids": representative[:10],
        "action": "label_review",
        "proposal_policy": "sidecar_only_manual_acceptance_required",
    }


def build_label_polish_review(*, run_root: Path | str, out: Path | str) -> dict[str, Any]:
    root = Path(run_root)
    out_root = ensure_optimization_output(out)
    review_items: list[dict[str, Any]] = []
    for node in _load_l2_nodes(root):
        reasons = review_label(str(node.get("label") or ""), representative_l1_ids=_representative_ids(node))
        if reasons:
            review_items.append(_review_item(node=node, node_type="l2_topic", reason_codes=reasons))
    for child in _load_child_nodes(root):
        reasons = review_label(str(child.get("label") or ""), representative_l1_ids=_representative_ids(child))
        if reasons:
            review_items.append(_review_item(node=child, node_type="child_l2_topic", reason_codes=reasons))

    reason_counts: dict[str, int] = {}
    for item in review_items:
        for code in item["reason_codes"]:
            reason_counts[code] = reason_counts.get(code, 0) + 1

    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "run_root": str(root.resolve()),
        "review_item_count": len(review_items),
        "reason_code_counts": reason_counts,
        "review_items": review_items,
        "decision": "label_polish_ready" if not review_items else "label_polish_review_needed",
        "canonical_mutation": False,
    }
    write_json(out_root / "summary.json", report)
    write_json(out_root / "label_polish_review_queue.json", {"items": review_items})
    write_text(out_root / "summary.md", _format_markdown(report))
    return report


def _format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Optimization V2 Label Polish Review",
        "",
        f"- decision: `{report.get('decision')}`",
        f"- review item count: `{report.get('review_item_count')}`",
        f"- run root: `{report.get('run_root')}`",
        "",
        "## Reason Codes",
        "",
    ]
    if report.get("reason_code_counts"):
        for code, count in sorted((report.get("reason_code_counts") or {}).items()):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Review Items", ""])
    for item in report.get("review_items", [])[:50]:
        lines.append(
            f"- `{item.get('item_type')}` `{item.get('l2_id') or item.get('child_l2_id')}` "
            f"label=`{item.get('label')}` reasons={', '.join(item.get('reason_codes', []))}"
        )
    if not report.get("review_items"):
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is a sidecar review queue only.",
            "- It does not rename L2/L3 nodes unless a later accepted-review step applies a candidate run.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sidecar label polish review for optimization v2 L2/L3.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_label_polish_review(run_root=args.run_root, out=args.out)
    print(
        "[optimization:v2] label polish review complete: "
        f"decision={report['decision']} review_items={report['review_item_count']}"
    )


if __name__ == "__main__":
    main()
