#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSCRIPT_DIR="${1:-"$ROOT_DIR/meeting_recording/transcript/ISCI"}"
MEETING_PREFIX="${MEETING_PREFIX:-Bmr}"
START_FROM_RAW="${START_FROM:-}"
START_FROM_MEETING=""

if [[ ! -d "$TRANSCRIPT_DIR" ]]; then
  echo "Transcript directory not found: $TRANSCRIPT_DIR" >&2
  exit 1
fi

if [[ -n "$START_FROM_RAW" ]]; then
  if [[ "$START_FROM_RAW" =~ ^[0-9]+$ ]]; then
    printf -v START_FROM_MEETING "%s%03d" "$MEETING_PREFIX" "$START_FROM_RAW"
  elif [[ "$START_FROM_RAW" =~ ^[0-9]{3}$ ]]; then
    START_FROM_MEETING="${MEETING_PREFIX}${START_FROM_RAW}"
  elif [[ "$START_FROM_RAW" =~ ^${MEETING_PREFIX}[0-9]{3}$ ]]; then
    START_FROM_MEETING="$START_FROM_RAW"
  else
    echo "Invalid START_FROM value: $START_FROM_RAW" >&2
    echo "Use formats like: 7, 007, or ${MEETING_PREFIX}007" >&2
    exit 1
  fi
fi

transcripts=()
while IFS= read -r transcript; do
  transcripts+=("$transcript")
done < <(
  find "$TRANSCRIPT_DIR" -maxdepth 1 -type f -name '*.txt' \
    | grep -E "/${MEETING_PREFIX}[0-9]{3}\\.txt$" \
    | sort
)

if [[ ${#transcripts[@]} -eq 0 ]]; then
  echo "No meeting transcript files found for prefix ${MEETING_PREFIX} in: $TRANSCRIPT_DIR" >&2
  exit 1
fi

selected_transcripts=()
for transcript in "${transcripts[@]}"; do
  meeting_file="$(basename "$transcript")"
  meeting_id="${meeting_file%.txt}"
  if [[ -n "$START_FROM_MEETING" && "$meeting_id" < "$START_FROM_MEETING" ]]; then
    continue
  fi
  selected_transcripts+=("$transcript")
done

if [[ ${#selected_transcripts[@]} -eq 0 ]]; then
  echo "No transcript files matched after START_FROM=${START_FROM_MEETING:-<empty>}" >&2
  exit 1
fi

echo "Found ${#selected_transcripts[@]} transcript(s) for prefix ${MEETING_PREFIX} in $TRANSCRIPT_DIR"
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
