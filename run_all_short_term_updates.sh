#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-"$ROOT_DIR/share_mem/snapshots"}"
SNAPSHOT_DIR="${1:-"$SNAPSHOT_DIR"}"
START_FROM_RAW="${START_FROM:-}"
START_FROM_MEETING=""

if [[ ! -d "$SNAPSHOT_DIR" ]]; then
  echo "Snapshot directory not found: $SNAPSHOT_DIR" >&2
  exit 1
fi

if [[ -n "$START_FROM_RAW" ]]; then
  START_FROM_MEETING="${START_FROM_RAW%.json}"
fi

meeting_is_before_start() {
  local meeting_id="$1"
  local start_id="$2"

  if [[ -z "$start_id" ]]; then
    return 1
  fi

  if [[ "$meeting_id" =~ ^[0-9]+$ && "$start_id" =~ ^[0-9]+$ ]]; then
    ((10#$meeting_id < 10#$start_id))
    return
  fi

  [[ "$meeting_id" < "$start_id" ]]
}

snapshot_filename_meeting_id() {
  local snapshot_file
  snapshot_file="$(basename "$1")"
  local meeting_id="${snapshot_file##*_bridge_}"
  printf '%s\n' "${meeting_id%.json}"
}

snapshot_latest_meeting_id() {
  local snapshot="$1"
  PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$snapshot" <<'PY'
import sys

from short_term.io_utils import normalize_str
from short_term.snapshot_loader import load_snapshot_tree, select_latest_meeting

snapshot_path = sys.argv[1]
meeting = select_latest_meeting(load_snapshot_tree(snapshot_path))
meeting_id = normalize_str(meeting.get("meeting_id"))
if not meeting_id:
    raise SystemExit(f"latest meeting is missing meeting_id: {snapshot_path}")
print(meeting_id)
PY
}

snapshots=()
while IFS= read -r snapshot; do
  snapshots+=("$snapshot")
done < <(
  find "$SNAPSHOT_DIR" -maxdepth 1 -type f -name '*_bridge_*.json' | sort -V
)

if [[ ${#snapshots[@]} -eq 0 ]]; then
  echo "No bridge snapshot JSON files found in: $SNAPSHOT_DIR" >&2
  exit 1
fi

selected_snapshots=()
selected_meeting_ids=()
declare -A selected_by_meeting=()
declare -A selected_filename_match_by_meeting=()

for snapshot in "${snapshots[@]}"; do
  meeting_id="$(snapshot_latest_meeting_id "$snapshot")"
  if meeting_is_before_start "$meeting_id" "$START_FROM_MEETING"; then
    continue
  fi

  filename_meeting_id="$(snapshot_filename_meeting_id "$snapshot")"
  filename_matches=0
  if [[ "$filename_meeting_id" == "$meeting_id" ]]; then
    filename_matches=1
  fi

  if [[ -z "${selected_by_meeting[$meeting_id]+x}" ]]; then
    selected_meeting_ids+=("$meeting_id")
    selected_by_meeting[$meeting_id]="$snapshot"
    selected_filename_match_by_meeting[$meeting_id]="$filename_matches"
    continue
  fi

  existing_matches="${selected_filename_match_by_meeting[$meeting_id]}"
  if [[ "$filename_matches" -gt "$existing_matches" || "$filename_matches" -eq "$existing_matches" ]]; then
    selected_by_meeting[$meeting_id]="$snapshot"
    selected_filename_match_by_meeting[$meeting_id]="$filename_matches"
  fi
done

for meeting_id in "${selected_meeting_ids[@]}"; do
  selected_snapshots+=("${selected_by_meeting[$meeting_id]}")
done

if [[ ${#selected_snapshots[@]} -eq 0 ]]; then
  echo "No snapshot files matched after START_FROM=${START_FROM_MEETING:-<empty>}" >&2
  exit 1
fi

echo "Found ${#snapshots[@]} bridge snapshot file(s) in $SNAPSHOT_DIR"
echo "Selected ${#selected_snapshots[@]} unique latest meeting snapshot(s)"
if [[ -n "$START_FROM_MEETING" ]]; then
  echo "Starting from ${START_FROM_MEETING}"
fi

for snapshot in "${selected_snapshots[@]}"; do
  echo
  echo "==> Processing $(basename "$snapshot")"
  (
    cd "$ROOT_DIR"
    uv run short_term/update_memory.py --snapshot "$snapshot"
  )
done

echo
echo "All snapshot updates completed."
