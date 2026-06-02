from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.io_utils import ensure_optimization_output, utc_now_iso, write_json, write_text
from optimization.long_term_v2.profiles import load_profile
from share_mem.store import iter_l1_objects, iter_meetings, load_share_tree


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _percentile(values: list[int | float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def calibrate_profile(
    *,
    share_mem_root: Path | str,
    profile: dict[str, Any],
    out_dir: Path | str,
) -> dict[str, Any]:
    out = ensure_optimization_output(out_dir)
    tree = load_share_tree(share_mem_root)
    meetings = list(iter_meetings(tree))
    objects = list(iter_l1_objects(tree))
    per_meeting_counts = [
        len([obj for obj in meeting.get("memory_objects", []) if isinstance(obj, dict)])
        for meeting in meetings
    ]
    importance_values = [_safe_float(obj.get("importance")) for _, obj in objects]
    type_counts = Counter(str(obj.get("type", "") or "") for _, obj in objects)
    topic_counts: Counter[str] = Counter()
    for _, obj in objects:
        for topic in obj.get("related_topics", []) or []:
            clean = str(topic).strip()
            if clean:
                topic_counts[clean] += 1

    l3_policy = dict(profile.get("l3_policy", {}) or {})
    p85 = _percentile(per_meeting_counts, 0.85)
    topic_size_hint = max(
        int(l3_policy.get("min_absolute_threshold", 10) or 10),
        int(round(p85 / 2)) if p85 else 10,
    )
    child_range = l3_policy.get("target_child_l2_size_range", [6, 28])
    report = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "profile_name": profile.get("name", ""),
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "meeting_count": len(meetings),
        "l1_count": len(objects),
        "l1_per_meeting": {
            "min": min(per_meeting_counts) if per_meeting_counts else 0,
            "max": max(per_meeting_counts) if per_meeting_counts else 0,
            "avg": round(statistics.mean(per_meeting_counts), 3) if per_meeting_counts else 0,
            "std_dev": round(statistics.pstdev(per_meeting_counts), 3) if len(per_meeting_counts) > 1 else 0,
            "p85": round(p85, 3),
        },
        "importance": {
            "avg": round(statistics.mean(importance_values), 3) if importance_values else 0,
            "p85": round(_percentile(importance_values, 0.85), 3),
        },
        "type_distribution": dict(sorted(type_counts.items())),
        "related_topic_top_30": dict(topic_counts.most_common(30)),
        "recommended_thresholds": {
            "l3_absolute_l1_threshold": topic_size_hint,
            "target_child_l2_size_min": int(child_range[0]) if child_range else 6,
            "target_child_l2_size_max": int(child_range[1]) if len(child_range) > 1 else 28,
        },
    }
    write_json(out / "profile_calibration.json", report)
    write_text(
        out / "profile_calibration.md",
        "\n".join(
            [
                "# Profile Calibration",
                "",
                f"- profile: `{report['profile_name']}`",
                f"- meetings: {report['meeting_count']}",
                f"- L1 objects: {report['l1_count']}",
                f"- average L1 per meeting: {report['l1_per_meeting']['avg']}",
                f"- recommended L3 threshold: {report['recommended_thresholds']['l3_absolute_l1_threshold']}",
                "",
            ]
        ),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate optimization long-term v2 profile thresholds.")
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    profile = load_profile(args.profile)
    report = calibrate_profile(
        share_mem_root=args.share_mem_root,
        profile=profile,
        out_dir=args.out,
    )
    print(
        f"[optimization:v2] calibration written: meetings={report['meeting_count']} l1={report['l1_count']}"
    )


if __name__ == "__main__":
    main()
