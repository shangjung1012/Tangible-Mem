#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSCRIPT_DIR="${TRANSCRIPT_DIR:-"$ROOT_DIR/meeting_recording/transcript/grace"}"
# TRANSCRIPT_DIR="${TRANSCRIPT_DIR:-"$ROOT_DIR/meeting_recording/transcript/ISCI"}"
TRANSCRIPT_DIR="${1:-"$TRANSCRIPT_DIR"}"
START_FROM_RAW="${START_FROM:-}"
START_FROM_MEETING=""

if [[ ! -d "$TRANSCRIPT_DIR" ]]; then
  echo "Transcript directory not found: $TRANSCRIPT_DIR" >&2
  exit 1
fi

if [[ -n "$START_FROM_RAW" ]]; then
  START_FROM_MEETING="${START_FROM_RAW%.txt}"
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

transcripts=()
while IFS= read -r transcript; do
  transcripts+=("$transcript")
done < <(
  find "$TRANSCRIPT_DIR" -maxdepth 1 -type f -name '*.txt' | sort -V
)

if [[ ${#transcripts[@]} -eq 0 ]]; then
  echo "No .txt transcript files found in: $TRANSCRIPT_DIR" >&2
  exit 1
fi

selected_transcripts=()
for transcript in "${transcripts[@]}"; do
  meeting_file="$(basename "$transcript")"
  meeting_id="${meeting_file%.txt}"
  if meeting_is_before_start "$meeting_id" "$START_FROM_MEETING"; then
    continue
  fi
  selected_transcripts+=("$transcript")
done

if [[ ${#selected_transcripts[@]} -eq 0 ]]; then
  echo "No transcript files matched after START_FROM=${START_FROM_MEETING:-<empty>}" >&2
  exit 1
fi

echo "Found ${#selected_transcripts[@]} transcript(s) in $TRANSCRIPT_DIR"
if [[ -n "$START_FROM_MEETING" ]]; then
  echo "Starting from ${START_FROM_MEETING}"
fi

for transcript in "${selected_transcripts[@]}"; do
  echo
  echo "==> Processing $(basename "$transcript")"
  (
    cd "$ROOT_DIR"
    uv run short_term/update_memory.py --transcript "$transcript"
  )
done

echo
echo "All transcript updates completed."
