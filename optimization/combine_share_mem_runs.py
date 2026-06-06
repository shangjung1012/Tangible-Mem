from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from optimization.output_roots import resolve_memory_run_root
from share_mem.store import load_share_tree, refresh_share_mem_outputs


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_unique_ids(meetings: list[dict[str, Any]]) -> None:
    meeting_ids: set[str] = set()
    obj_ids: set[str] = set()
    for meeting in meetings:
        meeting_id = str(meeting.get("meeting_id", "") or "").strip()
        if not meeting_id:
            raise ValueError("Meeting is missing meeting_id.")
        if meeting_id in meeting_ids:
            raise ValueError(f"Duplicate meeting_id: {meeting_id}")
        meeting_ids.add(meeting_id)
        for obj in meeting.get("memory_objects", []):
            obj_id = str(obj.get("obj_id", "") or "").strip()
            if not obj_id:
                raise ValueError(f"Object in {meeting_id} is missing obj_id.")
            if obj_id in obj_ids:
                raise ValueError(f"Duplicate obj_id: {obj_id}")
            obj_ids.add(obj_id)


def _source_summary(source_root: Path) -> dict[str, Any]:
    manifest_path = source_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.exists() else {}
    return {
        "source_root": str(source_root),
        "manifest_path": str(manifest_path) if manifest_path.exists() else "",
        "meeting_count": manifest.get("meeting_count"),
        "object_count": manifest.get("object_count"),
        "tree_hash": manifest.get("tree_hash"),
    }


def _resolve_imported_path(value: str, *, manifest_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    manifest_candidate = manifest_path.parent / path
    if manifest_candidate.exists():
        return manifest_candidate
    return cwd_candidate


def filtered_roots_from_archive_import_manifest(
    *,
    import_manifest: Path | str,
) -> list[Path]:
    manifest_path = Path(import_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    roots: list[Path] = []
    for row in manifest.get("imports", []) or []:
        if not isinstance(row, dict):
            continue
        imported_path = str(row.get("imported_path", "") or "").strip()
        if not imported_path:
            continue
        filtered_root = _resolve_imported_path(imported_path, manifest_path=manifest_path) / "filtered_share_mem"
        if not filtered_root.exists():
            raise FileNotFoundError(f"Missing filtered_share_mem for archive import: {filtered_root}")
        roots.append(filtered_root)
    if not roots:
        raise ValueError(f"No filtered_share_mem roots found in import manifest: {manifest_path}")
    return roots


def combine_share_mem_roots(
    *,
    source_roots: list[Path | str],
    output_root: Path | str,
    clean: bool = False,
) -> dict[str, Any]:
    output = Path(output_root)
    effective_root = output / "share_mem_effective"
    if clean and effective_root.exists():
        shutil.rmtree(effective_root)
    output.mkdir(parents=True, exist_ok=True)

    source_paths = [Path(root) for root in source_roots]
    if not source_paths:
        raise ValueError("At least one source root is required.")

    meetings: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    for source in source_paths:
        tree_path = source / "tree.json"
        if not tree_path.exists():
            raise FileNotFoundError(f"Missing share_mem tree: {tree_path}")
        tree = load_share_tree(source)
        meetings.extend([dict(meeting) for meeting in tree.get("meetings", [])])
        source_summaries.append(_source_summary(source))

    _validate_unique_ids(meetings)
    combined_tree = {
        "tree_version": 1,
        "last_updated_utc": _utc_now_iso(),
        "project_profile": {
            "source": "combined_effective_share_mem",
            "sidecar_only": True,
        },
        "phases": [],
        "meetings": meetings,
        "source_view": {
            "source": "combined_effective_share_mem",
            "sidecar_only": True,
            "source_roots": [str(path) for path in source_paths],
        },
    }
    manifest = refresh_share_mem_outputs(
        root=effective_root,
        tree=combined_tree,
        source_transcript_dir=None,
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": _utc_now_iso(),
        "mode": "combined_effective_share_mem",
        "output_root": str(output),
        "share_mem_effective_root": str(effective_root),
        "sources": source_summaries,
        "summary": {
            "source_count": len(source_paths),
            "meeting_count": manifest.get("meeting_count", 0),
            "object_count": manifest.get("object_count", 0),
            "meeting_ids": manifest.get("meeting_ids", []),
            "tree_hash": manifest.get("tree_hash", ""),
        },
    }
    _write_json(output / "combine_manifest.json", report)
    return report


def combine_archive_filtered_share_mem(
    *,
    import_manifest: Path | str,
    output_root: Path | str,
    clean: bool = False,
) -> dict[str, Any]:
    source_roots = filtered_roots_from_archive_import_manifest(import_manifest=import_manifest)
    report = combine_share_mem_roots(
        source_roots=source_roots,
        output_root=output_root,
        clean=clean,
    )
    report["mode"] = "combined_archive_filtered_share_mem"
    report["source_policy"] = {
        "archive_import_manifest": str(Path(import_manifest).resolve()),
        "filtered_share_mem_required": True,
        "raw_share_mem_ignored": True,
    }
    _write_json(Path(output_root) / "combine_manifest.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine effective share_mem roots into one sidecar run.")
    parser.add_argument("--source-root", action="append", default=[])
    parser.add_argument("--archive-import-manifest", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--output-base", default="")
    parser.add_argument("--dataset", default="icsi")
    parser.add_argument("--run-kind", default="archive_filtered_combined")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args(argv)


def config_output_root(args: argparse.Namespace) -> Path:
    if args.output_root:
        return Path(args.output_root)
    if not args.output_base:
        raise ValueError("Provide either --output-root or --output-base.")
    return resolve_memory_run_root(
        base_root=Path(args.output_base),
        dataset=str(args.dataset or "icsi"),
        run_kind=str(args.run_kind or "archive_filtered_combined"),
        run_id=str(args.run_id or "combined"),
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output_root = config_output_root(args)
    if args.archive_import_manifest:
        if args.source_root:
            raise ValueError("Use either --archive-import-manifest or --source-root, not both.")
        report = combine_archive_filtered_share_mem(
            import_manifest=args.archive_import_manifest,
            output_root=output_root,
            clean=bool(args.clean),
        )
    else:
        if not args.source_root:
            raise ValueError("Provide --source-root or --archive-import-manifest.")
        report = combine_share_mem_roots(
            source_roots=[Path(root) for root in args.source_root],
            output_root=output_root,
            clean=bool(args.clean),
        )
    summary = report["summary"]
    print(
        "[optimization] combined share_mem: "
        f"{summary['meeting_count']} meetings, "
        f"{summary['object_count']} L1 objects"
    )
    print(f"Output: {report['share_mem_effective_root']}")


if __name__ == "__main__":
    main()
