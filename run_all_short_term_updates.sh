#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSCRIPT_DIR="${1:-"$ROOT_DIR/ICSI_original_transcripts/transcripts"}"
MEETING_PREFIX="${MEETING_PREFIX:-Bmr}"

if [[ ! -d "$TRANSCRIPT_DIR" ]]; then
  echo "Transcript directory not found: $TRANSCRIPT_DIR" >&2
  exit 1
fi

transcripts=()
while IFS= read -r transcript; do
  transcripts+=("$transcript")
done < <(
  find "$TRANSCRIPT_DIR" -maxdepth 1 -type f -name '*.mrt' \
    | grep -E "/${MEETING_PREFIX}[0-9]{3}\\.mrt$" \
    | sort
)

if [[ ${#transcripts[@]} -eq 0 ]]; then
  echo "No meeting transcript files found for prefix ${MEETING_PREFIX} in: $TRANSCRIPT_DIR" >&2
  exit 1
fi

echo "Found ${#transcripts[@]} transcript(s) for prefix ${MEETING_PREFIX} in $TRANSCRIPT_DIR"

for transcript in "${transcripts[@]}"; do
  echo
  echo "==> Processing $(basename "$transcript")"
  (
    cd "$ROOT_DIR"
    uv run short_term/update_memory.py --transcript "$transcript"
  )
done

echo
echo "All transcript updates completed."
