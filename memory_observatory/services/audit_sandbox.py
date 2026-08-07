from __future__ import annotations

import copy
import difflib
import hashlib
from pathlib import Path
from typing import Any

from .retrieval_trace import RetrievalTraceService, _format_router_context
from .token_utils import context_token_metrics


class AuditSandboxService:
    """Build a non-persistent candidate retrieval context for UI inspection."""

    MAX_CORRECTED_STATE_CHARS = 1200
    MAX_DIFF_LINES = 180

    def __init__(self, repo_root: Path | str, dataset_id: str = "icsi") -> None:
        self.repo_root = Path(repo_root)
        self.dataset_id = dataset_id
        self.trace_service = RetrievalTraceService(self.repo_root, dataset_id=dataset_id)

    def preview(
        self,
        query: str,
        correction: dict[str, Any],
        *,
        retrieval_mode: str = "lexical",
        budget_profile: str = "observatory_paper_trace",
    ) -> dict[str, Any]:
        query_text = str(query or "").strip()
        if not query_text:
            raise ValueError("query is required")

        source_path = self.trace_service.loader.dataset.share_mem_root / "tree.json"
        source_hash_before = _file_sha256(source_path)
        baseline = self.trace_service.run_trace(
            query=query_text,
            retrieval_mode=retrieval_mode,
            no_llm=True,
            include_debug=False,
            budget_profile=budget_profile,
            max_context_chars=0,
        )
        result = self.preview_from_trace(baseline, correction)
        source_hash_after = _file_sha256(source_path)
        source_tree_verified = bool(source_hash_before and source_hash_after)
        result["impact"]["source_tree_verified"] = source_tree_verified
        result["impact"]["raw_evidence_unchanged"] = (
            source_tree_verified and source_hash_before == source_hash_after
        )
        result["impact"]["source_tree_sha256"] = source_hash_after
        return result

    def preview_from_trace(
        self,
        baseline_trace: dict[str, Any],
        correction: dict[str, Any],
    ) -> dict[str, Any]:
        raw_result = baseline_trace.get("raw_recall_result")
        if not isinstance(raw_result, dict):
            raise ValueError("baseline trace does not include structured recall data")

        target_l2_id = str(correction.get("target_l2_id") or "").strip()
        corrected_state = str(correction.get("corrected_state") or "").strip()
        reason_code = str(correction.get("reason_code") or "other").strip()
        excluded_ids = {
            str(obj_id).strip()
            for obj_id in correction.get("exclude_obj_ids", [])
            if str(obj_id).strip()
        }
        if len(corrected_state) > self.MAX_CORRECTED_STATE_CHARS:
            raise ValueError(
                f"corrected_state exceeds {self.MAX_CORRECTED_STATE_CHARS} characters"
            )
        if not corrected_state and not excluded_ids:
            raise ValueError("provide a corrected topic state or exclude at least one L1 object")

        baseline_l1 = baseline_trace.get("l1_evidence_seeds", [])
        selected_ids = {
            str(item.get("obj_id") or "")
            for item in baseline_l1
            if isinstance(item, dict) and item.get("obj_id")
        }
        unknown_exclusions = sorted(excluded_ids - selected_ids)
        if unknown_exclusions:
            raise ValueError(
                "excluded L1 objects are not present in the baseline trace: "
                + ", ".join(unknown_exclusions)
            )

        candidate_raw = copy.deepcopy(raw_result)
        changed_l2_ids: list[str] = []
        previous_state = ""
        if corrected_state:
            matched_topic = None
            for topic in candidate_raw.get("long_term_l2", []):
                if isinstance(topic, dict) and str(topic.get("l2_id") or "") == target_l2_id:
                    matched_topic = topic
                    break
            if matched_topic is None:
                raise ValueError(f"target L2 topic is not present in the baseline trace: {target_l2_id}")
            previous_state = str(
                matched_topic.get("current_state")
                or matched_topic.get("evolution_summary")
                or ""
            )
            matched_topic["current_state"] = corrected_state
            matched_topic["evolution_summary"] = ""
            matched_topic["latest_position"] = ""
            matched_topic["audit_correction"] = {
                "scope": "session_only",
                "reason_code": reason_code,
            }
            changed_l2_ids.append(target_l2_id)

        if excluded_ids:
            candidate_raw["long_term_l1"] = [
                item
                for item in candidate_raw.get("long_term_l1", [])
                if not isinstance(item, dict) or str(item.get("obj_id") or "") not in excluded_ids
            ]
            for topic in candidate_raw.get("long_term_l2", []):
                if not isinstance(topic, dict):
                    continue
                if isinstance(topic.get("matched_l1_ids"), list):
                    topic["matched_l1_ids"] = [
                        obj_id for obj_id in topic["matched_l1_ids"] if str(obj_id) not in excluded_ids
                    ]
                if isinstance(topic.get("timeline_digest"), list):
                    topic["timeline_digest"] = [
                        event
                        for event in topic["timeline_digest"]
                        if not isinstance(event, dict)
                        or str(event.get("obj_id") or "") not in excluded_ids
                    ]
                    topic["selected_event_count"] = len(topic["timeline_digest"])
            debug = candidate_raw.get("retrieval_debug")
            if isinstance(debug, dict):
                debug["selected_l1_count"] = len(candidate_raw.get("long_term_l1", []))

        candidate_context = _format_candidate_context(candidate_raw, baseline_trace)
        baseline_context = str(baseline_trace.get("formatted_prompt_context") or "")
        before_metrics = context_token_metrics(baseline_context)
        after_metrics = context_token_metrics(candidate_context)
        diff_lines, diff_truncated = _context_diff(
            baseline_context,
            candidate_context,
            max_lines=self.MAX_DIFF_LINES,
        )

        candidate_l1 = candidate_raw.get("long_term_l1", [])
        candidate_l2 = candidate_raw.get("long_term_l2", [])
        return {
            "dataset_id": baseline_trace.get("dataset_id", self.dataset_id),
            "query": baseline_trace.get("query", ""),
            "scope": "session_only",
            "persisted": False,
            "baseline": {
                "l1_evidence_seeds": baseline_l1,
                "l2_evolution_context": baseline_trace.get("l2_evolution_context", []),
                "formatted_prompt_context": baseline_context,
                "metrics": before_metrics,
            },
            "candidate": {
                "l1_evidence_seeds": candidate_l1,
                "l2_evolution_context": candidate_l2,
                "formatted_prompt_context": candidate_context,
                "metrics": after_metrics,
            },
            "correction": {
                "target_l2_id": target_l2_id,
                "previous_state": previous_state,
                "corrected_state": corrected_state,
                "reason_code": reason_code,
                "excluded_l1_ids": sorted(excluded_ids),
            },
            "impact": {
                "query_unchanged": True,
                "prompt_chars_before": len(baseline_context),
                "prompt_chars_after": len(candidate_context),
                "prompt_chars_delta": len(candidate_context) - len(baseline_context),
                "prompt_tokens_before": before_metrics["estimated_context_tokens"],
                "prompt_tokens_after": after_metrics["estimated_context_tokens"],
                "prompt_tokens_delta": (
                    after_metrics["estimated_context_tokens"]
                    - before_metrics["estimated_context_tokens"]
                ),
                "l1_count_before": len(baseline_l1),
                "l1_count_after": len(candidate_l1),
                "excluded_l1_ids": sorted(excluded_ids),
                "changed_l2_ids": changed_l2_ids,
                "raw_evidence_unchanged": True,
                "answer_generated": False,
                "answer_verification_status": "pending_vertex_ai",
            },
            "context_diff": diff_lines,
            "context_diff_truncated": diff_truncated,
        }


def _format_candidate_context(
    recall_result: dict[str, Any],
    baseline_trace: dict[str, Any],
) -> str:
    from recall import format_recall_for_prompt

    formatted = format_recall_for_prompt(
        recall_result,
        include_debug=False,
        l1_content_chars=320,
        l1_evidence_chars=420,
    )
    parts = [_format_router_context(baseline_trace.get("router_result", {}))]
    current_state_context = str(baseline_trace.get("current_implementation_state") or "").strip()
    if current_state_context:
        parts.append(current_state_context)
    parts.append(formatted)
    return "\n\n".join(part for part in parts if part)


def _context_diff(
    before: str,
    after: str,
    *,
    max_lines: int,
) -> tuple[list[dict[str, str]], bool]:
    raw_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="baseline",
            tofile="candidate",
            lineterm="",
            n=2,
        )
    )
    truncated = len(raw_lines) > max_lines
    rows: list[dict[str, str]] = []
    for line in raw_lines[:max_lines]:
        if line.startswith("+++") or line.startswith("---"):
            kind = "header"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "remove"
        elif line.startswith("@@"):
            kind = "hunk"
        else:
            kind = "context"
        rows.append({"kind": kind, "text": line})
    return rows, truncated


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
