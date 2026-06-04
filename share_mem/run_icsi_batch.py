from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .store import load_share_tree, refresh_share_mem_outputs
    from .validate_icsi_l1 import write_icsi_l1_quality_report, write_icsi_l1_review_gate
except ImportError:  # pragma: no cover - direct script execution fallback
    from store import load_share_tree, refresh_share_mem_outputs  # type: ignore
    from validate_icsi_l1 import (  # type: ignore
        write_icsi_l1_quality_report,
        write_icsi_l1_review_gate,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSCRIPT_DIR = REPO_ROOT / "meeting_recording" / "transcript" / "ISCI"
DEFAULT_MODEL = "gemini-2.5-pro"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp_for_path() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class BatchConfig:
    transcript_dir: Path
    output_root: Path
    model: str = DEFAULT_MODEL
    dataset_profile: str = "isci"
    taxonomy: str = "v2-memory-roles"
    include_legacy_type: bool = True
    content_language: str = "english"
    window_size: int = 120
    lookback_lines: int = 10
    lookahead_lines: int = 10
    previous_context: bool = False
    use_dataset_guidance: bool = False
    line_limit: int | None = None
    timeout_seconds: int = 7200
    transcript_glob: str = "*.txt"
    max_files: int | None = None
    resume: bool = False
    continue_on_failure: bool = False
    dry_run: bool = False
    clean: bool = False
    python_executable: str = field(default_factory=lambda: sys.executable)

    @property
    def share_mem_root(self) -> Path:
        return self.output_root / "share_mem"

    @property
    def input_root(self) -> Path:
        return self.output_root / "input_transcripts"

    @property
    def orchestration_log_root(self) -> Path:
        return self.output_root / "orchestration_logs"

    @property
    def validation_root(self) -> Path:
        return self.output_root / "validation"

    @property
    def filtered_share_mem_root(self) -> Path:
        return self.output_root / "filtered_share_mem"

    @property
    def status_path(self) -> Path:
        return self.output_root / "batch_status.json"


def validate_output_root_safety(output_root: Path | str) -> Path:
    resolved = Path(output_root).resolve()
    canonical_share_mem = (REPO_ROOT / "share_mem").resolve()
    if resolved == canonical_share_mem or canonical_share_mem in resolved.parents:
        raise ValueError("ICSI batch output_root must not be canonical share_mem/.")
    return resolved


def discover_transcripts(config: BatchConfig) -> list[Path]:
    transcripts = sorted(config.transcript_dir.glob(config.transcript_glob), key=lambda path: path.name)
    if config.max_files is not None:
        transcripts = transcripts[: max(0, config.max_files)]
    return transcripts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_transcript_input(
    *,
    transcript_path: Path,
    input_root: Path,
    line_limit: int | None,
) -> Path:
    if line_limit is None:
        return transcript_path
    input_root.mkdir(parents=True, exist_ok=True)
    limited_name = f"{transcript_path.stem}_first{line_limit}{transcript_path.suffix}"
    limited_path = input_root / limited_name
    lines = transcript_path.read_text(encoding="utf-8").splitlines(keepends=True)
    limited_path.write_text("".join(lines[:line_limit]), encoding="utf-8")
    return limited_path


def build_bridge_command(config: BatchConfig, transcript_path: Path) -> list[str]:
    command = [
        config.python_executable,
        "-m",
        "share_mem.l1.bridge",
        "--transcript",
        str(transcript_path),
        "--tree",
        str(config.share_mem_root / "tree.json"),
        "--snapshot-dir",
        str(config.share_mem_root / "snapshots"),
        "--research-log-dir",
        str(config.share_mem_root / "research_logs"),
        "--mode",
        "multi-agent",
        "--dataset-profile",
        config.dataset_profile,
        "--model",
        config.model,
        "--taxonomy",
        config.taxonomy,
        "--content-language",
        config.content_language,
        "--multi-agent-window-size",
        str(config.window_size),
        "--multi-agent-lookback-lines",
        str(config.lookback_lines),
        "--multi-agent-lookahead-lines",
        str(config.lookahead_lines),
    ]
    if config.include_legacy_type:
        command.append("--include-legacy-type")
    if config.previous_context:
        command.append("--multi-agent-previous-context")
    if config.use_dataset_guidance:
        command.append("--use-dataset-guidance")
    return command


def _load_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "runs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clean_output(config: BatchConfig) -> None:
    for child in [
        config.share_mem_root,
        config.filtered_share_mem_root,
        config.input_root,
        config.orchestration_log_root,
        config.validation_root,
    ]:
        if child.exists():
            shutil.rmtree(child)
    if config.status_path.exists():
        config.status_path.unlink()


def _completed_source_hashes(status: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for run in status.get("runs", []):
        if run.get("status") == "succeeded":
            hashes[str(run.get("source_path", ""))] = str(run.get("source_sha256", ""))
    return hashes


def _refresh_share_mem(config: BatchConfig) -> dict[str, Any]:
    tree = load_share_tree(config.share_mem_root)
    return refresh_share_mem_outputs(
        root=config.share_mem_root,
        tree=tree,
        source_transcript_dir=config.transcript_dir,
    )


def build_filtered_share_tree(tree: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    """Return an ICSI effective-L1 tree without mutating the raw L1 tree.

    The raw extraction output remains under ``share_mem/``. This sidecar tree is
    for downstream L2/L3 experiments that should ignore review-gated source-data
    noise while keeping every retained object in normal share_mem shape.
    """
    allowed = {str(obj_id) for obj_id in gate.get("filtered_candidate_obj_ids", [])}
    filtered_tree = dict(tree)
    filtered_meetings: list[dict[str, Any]] = []
    for meeting in tree.get("meetings", []):
        if not isinstance(meeting, dict):
            continue
        meeting_copy = dict(meeting)
        meeting_copy["memory_objects"] = [
            dict(obj)
            for obj in meeting.get("memory_objects", [])
            if str(obj.get("obj_id", "")) in allowed
        ]
        filtered_meetings.append(meeting_copy)
    filtered_tree["meetings"] = filtered_meetings
    filtered_tree["source_view"] = {
        "source": "icsi_l1_review_gate",
        "sidecar_only": True,
        "raw_tree_object_count": sum(
            len(meeting.get("memory_objects", []))
            for meeting in tree.get("meetings", [])
            if isinstance(meeting, dict)
        ),
        "filtered_object_count": sum(len(meeting["memory_objects"]) for meeting in filtered_meetings),
    }
    return filtered_tree


def _refresh_filtered_share_mem(config: BatchConfig, gate: dict[str, Any]) -> dict[str, Any]:
    tree = load_share_tree(config.share_mem_root)
    filtered_tree = build_filtered_share_tree(tree, gate)
    manifest = refresh_share_mem_outputs(
        root=config.filtered_share_mem_root,
        tree=filtered_tree,
        source_transcript_dir=config.transcript_dir,
    )
    manifest["source_view"] = filtered_tree.get("source_view", {})
    _write_json(config.filtered_share_mem_root / "manifest.json", manifest)
    return manifest


def _run_validation(config: BatchConfig, label: str) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    tree = load_share_tree(config.share_mem_root)
    for meeting in tree.get("meetings", []):
        meeting_id = str(meeting.get("meeting_id", ""))
        for obj in meeting.get("memory_objects", []):
            row = dict(obj)
            row.setdefault("meeting_id", meeting_id)
            objects.append(row)
    out = config.validation_root / label
    quality = write_icsi_l1_quality_report(objects, out)
    gate = write_icsi_l1_review_gate(objects, out)
    filtered_manifest = _refresh_filtered_share_mem(config, gate)
    return {
        "validation_dir": str(out),
        "quality_summary": quality.get("summary", {}),
        "review_gate_summary": gate.get("summary", {}),
        "filtered_share_mem_root": str(config.filtered_share_mem_root),
        "filtered_manifest": {
            "meeting_count": filtered_manifest.get("meeting_count"),
            "object_count": filtered_manifest.get("object_count"),
            "tree_hash": filtered_manifest.get("tree_hash"),
            "source_view": filtered_manifest.get("source_view", {}),
        },
    }


def _run_command(
    *,
    command: list[str],
    timeout_seconds: int,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[str, int | None, str]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                stdout=stdout,
                stderr=stderr,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - started
            return "timed_out", None, f"Timed out after {timeout_seconds}s ({elapsed:.1f}s elapsed)."
    if completed.returncode == 0:
        return "succeeded", completed.returncode, ""
    return "failed", completed.returncode, f"Command exited with {completed.returncode}."


def run_batch(config: BatchConfig) -> dict[str, Any]:
    config.output_root = validate_output_root_safety(config.output_root)
    config.output_root.mkdir(parents=True, exist_ok=True)
    if config.clean:
        _clean_output(config)
    config.share_mem_root.mkdir(parents=True, exist_ok=True)

    transcripts = discover_transcripts(config)
    if not transcripts:
        raise RuntimeError(f"No transcripts matched {config.transcript_glob} under {config.transcript_dir}")

    status = _load_status(config.status_path)
    status.update(
        {
            "schema_version": 1,
            "updated_at_utc": _utc_now_iso(),
            "config": {
                "transcript_dir": str(config.transcript_dir),
                "output_root": str(config.output_root),
                "dataset_profile": config.dataset_profile,
                "taxonomy": config.taxonomy,
                "include_legacy_type": config.include_legacy_type,
                "content_language": config.content_language,
                "window_size": config.window_size,
                "lookback_lines": config.lookback_lines,
                "lookahead_lines": config.lookahead_lines,
                "previous_context": config.previous_context,
                "line_limit": config.line_limit,
                "timeout_seconds": config.timeout_seconds,
                "transcript_glob": config.transcript_glob,
                "max_files": config.max_files,
                "resume": config.resume,
                "continue_on_failure": config.continue_on_failure,
                "dry_run": config.dry_run,
            },
        }
    )
    runs = status.setdefault("runs", [])
    completed_hashes = _completed_source_hashes(status) if config.resume else {}

    for source_path in transcripts:
        source_hash = sha256_file(source_path)
        if config.resume and completed_hashes.get(str(source_path)) == source_hash:
            runs.append(
                {
                    "meeting_source": source_path.name,
                    "source_path": str(source_path),
                    "source_sha256": source_hash,
                    "status": "skipped",
                    "reason": "resume_source_hash_match",
                    "updated_at_utc": _utc_now_iso(),
                }
            )
            _write_json(config.status_path, status)
            continue

        prepared_path = prepare_transcript_input(
            transcript_path=source_path,
            input_root=config.input_root,
            line_limit=config.line_limit,
        )
        meeting_id = prepared_path.stem
        stdout_path = config.orchestration_log_root / f"{meeting_id}.stdout.log"
        stderr_path = config.orchestration_log_root / f"{meeting_id}.stderr.log"
        command = build_bridge_command(config, prepared_path)
        run_record: dict[str, Any] = {
            "meeting_id": meeting_id,
            "meeting_source": source_path.name,
            "source_path": str(source_path),
            "prepared_path": str(prepared_path),
            "source_sha256": source_hash,
            "command": command,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "started_at_utc": _utc_now_iso(),
            "status": "running",
        }
        runs.append(run_record)
        _write_json(config.status_path, status)

        if config.dry_run:
            run_record.update({"status": "dry_run", "finished_at_utc": _utc_now_iso()})
            _write_json(config.status_path, status)
            continue

        started = time.monotonic()
        result_status, returncode, error = _run_command(
            command=command,
            timeout_seconds=config.timeout_seconds,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        run_record.update(
            {
                "status": result_status,
                "returncode": returncode,
                "error": error,
                "duration_seconds": round(time.monotonic() - started, 3),
                "finished_at_utc": _utc_now_iso(),
            }
        )
        if result_status == "succeeded":
            manifest = _refresh_share_mem(config)
            validation = _run_validation(config, f"after_{meeting_id}")
            run_record["manifest_after_run"] = {
                "meeting_count": manifest.get("meeting_count"),
                "object_count": manifest.get("object_count"),
            }
            run_record["validation_after_run"] = validation
        _write_json(config.status_path, status)
        if result_status != "succeeded" and not config.continue_on_failure:
            break

    status["updated_at_utc"] = _utc_now_iso()
    status["summary"] = {
        "selected_transcript_count": len(transcripts),
        "succeeded_count": sum(1 for run in runs if run.get("status") == "succeeded"),
        "failed_count": sum(1 for run in runs if run.get("status") == "failed"),
        "timed_out_count": sum(1 for run in runs if run.get("status") == "timed_out"),
        "skipped_count": sum(1 for run in runs if run.get("status") == "skipped"),
        "dry_run_count": sum(1 for run in runs if run.get("status") == "dry_run"),
    }
    _write_json(config.status_path, status)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ICSI L1 extraction one transcript at a time.")
    parser.add_argument("--transcript-dir", default=str(DEFAULT_TRANSCRIPT_DIR))
    parser.add_argument("--output-root", default="")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dataset-profile", default="isci")
    parser.add_argument("--taxonomy", choices=["v1", "v2-memory-roles"], default="v2-memory-roles")
    parser.add_argument("--no-legacy-type", action="store_true")
    parser.add_argument("--content-language", choices=["traditional_zh", "english"], default="english")
    parser.add_argument("--window-size", type=int, default=120)
    parser.add_argument("--lookback-lines", type=int, default=10)
    parser.add_argument("--lookahead-lines", type=int, default=10)
    parser.add_argument("--previous-context", action="store_true")
    parser.add_argument("--use-dataset-guidance", action="store_true")
    parser.add_argument("--line-limit", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--transcript-glob", default="*.txt")
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> BatchConfig:
    output_root = Path(args.output_root) if args.output_root else (
        REPO_ROOT / "share_mem_experiments" / f"icsi_l1_batch_{_timestamp_for_path()}"
    )
    return BatchConfig(
        transcript_dir=Path(args.transcript_dir),
        output_root=output_root,
        model=str(args.model),
        dataset_profile=str(args.dataset_profile),
        taxonomy=str(args.taxonomy),
        include_legacy_type=not bool(args.no_legacy_type),
        content_language=str(args.content_language),
        window_size=int(args.window_size),
        lookback_lines=int(args.lookback_lines),
        lookahead_lines=int(args.lookahead_lines),
        previous_context=bool(args.previous_context),
        use_dataset_guidance=bool(args.use_dataset_guidance),
        line_limit=args.line_limit,
        timeout_seconds=int(args.timeout_seconds),
        transcript_glob=str(args.transcript_glob),
        max_files=args.max_files,
        resume=bool(args.resume),
        continue_on_failure=bool(args.continue_on_failure),
        dry_run=bool(args.dry_run),
        clean=bool(args.clean),
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = config_from_args(args)
    status = run_batch(config)
    print(
        "[share_mem] ICSI batch status: "
        f"{status['summary']['succeeded_count']} succeeded, "
        f"{status['summary']['failed_count']} failed, "
        f"{status['summary']['timed_out_count']} timed out"
    )
    print(f"Status: {config.status_path}")


if __name__ == "__main__":
    main()
