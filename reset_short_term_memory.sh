#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHORT_TERM_DIR="$ROOT_DIR/short_term"

YES=0
DRY_RUN=0
KEEP_LOGS=0
KEEP_RESEARCH_LOGS=0
KEEP_SNAPSHOTS=0
KEEP_TRANSCRIPT_DB=0
KEEP_CHECKPOINTS=0

usage() {
  cat <<'EOF'
Reset short_term runtime memory state.

This deletes generated short-term memory/runtime artifacts only. It does not
delete source transcripts under meeting_recording/.

Usage:
  ./reset_short_term_memory.sh --yes
  ./reset_short_term_memory.sh --dry-run

Options:
  --yes                 Do not prompt before deleting.
  --dry-run             Print what would be deleted without deleting.
  --keep-logs           Keep short_term/logs/*.log.
  --keep-research-logs  Keep short_term/research_logs/.
  --keep-snapshots      Keep short_term/snapshots/ and short_term/db_snapshots/.
  --keep-transcript-db  Keep short_term/storage/transcripts.db.
  --keep-checkpoints    Keep short_term/langgraph_checkpoints.db.
  -h, --help            Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      YES=1
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --keep-logs)
      KEEP_LOGS=1
      ;;
    --keep-research-logs)
      KEEP_RESEARCH_LOGS=1
      ;;
    --keep-snapshots)
      KEEP_SNAPSHOTS=1
      ;;
    --keep-transcript-db)
      KEEP_TRANSCRIPT_DB=1
      ;;
    --keep-checkpoints)
      KEEP_CHECKPOINTS=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -d "$SHORT_TERM_DIR" ]]; then
  echo "short_term directory not found: $SHORT_TERM_DIR" >&2
  exit 1
fi

paths=(
  "$SHORT_TERM_DIR/short_term_memory.db"
  "$SHORT_TERM_DIR/short_term_memory.db-wal"
  "$SHORT_TERM_DIR/short_term_memory.db-shm"
  "$SHORT_TERM_DIR/short_term_memory.json"
  "$SHORT_TERM_DIR/current_memory.json"
)

while IFS= read -r backup_db; do
  paths+=("$backup_db")
done < <(
  find "$SHORT_TERM_DIR" -maxdepth 1 -type f \
    \( -name 'short_term_memory.before_*.db' -o -name 'short_term_memory.*.backup.db' \) \
    | sort
)

if [[ "$KEEP_TRANSCRIPT_DB" -eq 0 ]]; then
  paths+=(
    "$SHORT_TERM_DIR/storage/transcripts.db"
    "$SHORT_TERM_DIR/storage/transcripts.db-wal"
    "$SHORT_TERM_DIR/storage/transcripts.db-shm"
  )
fi

if [[ "$KEEP_CHECKPOINTS" -eq 0 ]]; then
  paths+=(
    "$SHORT_TERM_DIR/langgraph_checkpoints.db"
    "$SHORT_TERM_DIR/langgraph_checkpoints.db-wal"
    "$SHORT_TERM_DIR/langgraph_checkpoints.db-shm"
  )
fi

dirs_to_empty=()
if [[ "$KEEP_LOGS" -eq 0 ]]; then
  dirs_to_empty+=("$SHORT_TERM_DIR/logs")
fi
if [[ "$KEEP_RESEARCH_LOGS" -eq 0 ]]; then
  dirs_to_empty+=("$SHORT_TERM_DIR/research_logs")
fi
if [[ "$KEEP_SNAPSHOTS" -eq 0 ]]; then
  dirs_to_empty+=("$SHORT_TERM_DIR/snapshots")
  dirs_to_empty+=("$SHORT_TERM_DIR/db_snapshots")
fi

echo "short_term reset target:"
echo "  repo: $ROOT_DIR"
echo "  memory DB: $SHORT_TERM_DIR/short_term_memory.db"
echo
echo "Files to delete if present:"
for path in "${paths[@]}"; do
  echo "  $path"
done
echo
echo "Directories to empty if present:"
for dir in "${dirs_to_empty[@]}"; do
  echo "  $dir"
done
echo
echo "Source transcripts are not touched."

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "Dry run only; no files deleted."
  exit 0
fi

if [[ "$YES" -ne 1 ]]; then
  if [[ ! -t 0 ]]; then
    echo "Refusing to delete in non-interactive mode without --yes." >&2
    exit 2
  fi
  printf "Delete these generated short_term artifacts? [y/N] "
  read -r answer
  case "$answer" in
    y|Y|yes|YES)
      ;;
    *)
      echo "Aborted."
      exit 0
      ;;
  esac
fi

for path in "${paths[@]}"; do
  rm -f "$path"
done

for dir in "${dirs_to_empty[@]}"; do
  if [[ -d "$dir" ]]; then
    find "$dir" -mindepth 1 -maxdepth 1 ! -name ".gitignore" -exec rm -rf -- {} +
  fi
done

echo "short_term runtime memory state reset."
echo "Next run will start from an empty canonical memory DB."
