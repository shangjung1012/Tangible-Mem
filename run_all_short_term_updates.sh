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
for snapshot in "${snapshots[@]}"; do
  snapshot_file="$(basename "$snapshot")"
  meeting_id="${snapshot_file##*_bridge_}"
  meeting_id="${meeting_id%.json}"
  if meeting_is_before_start "$meeting_id" "$START_FROM_MEETING"; then
    continue
  fi
  selected_snapshots+=("$snapshot")
done

if [[ ${#selected_snapshots[@]} -eq 0 ]]; then
  echo "No snapshot files matched after START_FROM=${START_FROM_MEETING:-<empty>}" >&2
  exit 1
fi

echo "Found ${#selected_snapshots[@]} snapshot(s) in $SNAPSHOT_DIR"
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
