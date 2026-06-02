from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.long_term_v2.assign_l2 import assign_l2_topics
from optimization.long_term_v2.calibrate_profile import calibrate_profile
from optimization.long_term_v2.extract_semantic_keys import build_semantic_key_index
from optimization.long_term_v2.io_utils import (
    copy_input_snapshot,
    ensure_optimization_output,
    tree_hash,
    utc_now_iso,
    write_json,
    write_text,
)
from optimization.long_term_v2.induce_l2_topics import write_l2_outputs
from optimization.long_term_v2.llm_topic_refinement import refine_l2_result_with_llm
from optimization.long_term_v2.profiles import load_profile
from optimization.long_term_v2.promote_l3 import build_l3_view, write_l3_outputs
from share_mem.store import iter_l1_objects, load_share_tree


SUPPORTED_MODES = {"deterministic", "llm-assisted"}


def _prepare_run_root(out_root: Path, *, clean: bool) -> Path:
    resolved = ensure_optimization_output(out_root)
    if clean and resolved.exists():
        shutil.rmtree(resolved)
        resolved.mkdir(parents=True, exist_ok=True)
    else:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _write_semantic_outputs(run_root: Path, semantic_index: dict[str, Any]) -> None:
    semantic_dir = run_root / "semantic_keys"
    write_json(semantic_dir / "semantic_key_index.json", semantic_index)
    write_text(
        semantic_dir / "semantic_key_summary.md",
        "\n".join(
            [
                "# Semantic Key Summary",
                "",
                f"- objects: {semantic_index['object_count']}",
                f"- profile: `{semantic_index['profile_name']}`",
                "",
            ]
        ),
    )


def build_view(
    *,
    share_mem_root: Path | str,
    profile_path: Path | str,
    out_root: Path | str,
    mode: str = "deterministic",
    model: str = "",
    clean: bool = False,
) -> dict[str, Any]:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"unsupported optimization v2 mode: {mode}")
    run_root = _prepare_run_root(Path(out_root), clean=clean)
    profile = load_profile(profile_path)
    tree = load_share_tree(share_mem_root)
    source_hash_before = tree_hash(tree)
    copy_input_snapshot(share_mem_root=share_mem_root, run_root=run_root)

    calibration = calibrate_profile(
        share_mem_root=share_mem_root,
        profile=profile,
        out_dir=run_root / "calibration",
    )
    semantic_index = build_semantic_key_index(tree, profile)
    _write_semantic_outputs(run_root, semantic_index)

    l2_result = assign_l2_topics(
        tree=tree,
        semantic_key_index=semantic_index,
        profile=profile,
    )
    llm_usage = {
        "requested": mode == "llm-assisted",
        "used": False,
        "status": "deterministic_fallback_v1" if mode == "llm-assisted" else "not_requested",
    }
    if mode == "llm-assisted":
        l2_result, llm_usage = refine_l2_result_with_llm(
            l2_result=l2_result,
            profile=profile,
            run_root=run_root,
            model=model,
        )
    write_l2_outputs(out_dir=run_root, l2_result=l2_result)

    l3_result = build_l3_view(l2_result=l2_result, profile=profile)
    write_l3_outputs(out_dir=run_root, l3_result=l3_result)

    object_count = len(list(iter_l1_objects(tree)))
    manifest = {
        "schema_version": 1,
        "generated_at_utc": utc_now_iso(),
        "source": "optimization_long_term_v2",
        "mode": mode,
        "model": model,
        "llm_usage": llm_usage,
        "share_mem_root": str(Path(share_mem_root).resolve()),
        "profile_path": str(Path(profile_path).resolve()),
        "profile_name": profile.get("name", ""),
        "source_tree_hash_before": source_hash_before,
        "source_l1_count": object_count,
        "semantic_key_count": semantic_index["object_count"],
        "l2_topic_count": len(l2_result["l2_nodes"]),
        "linked_l1_count": len(l2_result["l2_index"]),
        "unlinked_l1_count": len(l2_result["unlinked_objects"]),
        "l3_parent_count": len(l3_result["l3_parents"]),
        "l3_assigned_l1_count": len(l3_result["l3_index"]),
        "output_contract": "all generated outputs are confined to this optimization run root",
        "calibration": calibration.get("recommended_thresholds", {}),
    }
    write_json(run_root / "manifest.json", manifest)
    write_text(
        run_root / "README.md",
        "\n".join(
            [
                "# Optimization Long-Term v2 Run",
                "",
                f"- profile: `{manifest['profile_name']}`",
                f"- mode: `{mode}`",
                f"- source L1 count: {object_count}",
                f"- L2 topics: {manifest['l2_topic_count']}",
                f"- L3 parents: {manifest['l3_parent_count']}",
                "",
                "This run is side-by-side only and does not promote outputs to canonical long_term artifacts.",
                "",
            ]
        ),
    )
    return {
        "manifest": manifest,
        "semantic_key_index": semantic_index,
        "l2_result": l2_result,
        "l3_result": l3_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build isolated optimization long-term v2 L2/L3 views.")
    parser.add_argument("--share-mem-root", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=sorted(SUPPORTED_MODES), default="deterministic")
    parser.add_argument("--model", default="")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    result = build_view(
        share_mem_root=args.share_mem_root,
        profile_path=args.profile,
        out_root=args.out,
        mode=args.mode,
        model=args.model,
        clean=args.clean,
    )
    manifest = result["manifest"]
    print(
        "[optimization:v2] build complete: "
        f"l1={manifest['source_l1_count']} l2={manifest['l2_topic_count']} "
        f"l3={manifest['l3_parent_count']} out={Path(args.out).resolve()}"
    )


if __name__ == "__main__":
    main()
