from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
INPUT_DIR = REPO_ROOT / "ICSI_original_transcripts" / "transcripts"
OUTPUT_DIR = SCRIPT_DIR

SPACE_RE = re.compile(r"\s+")
LETTER_UNDERSCORE_RE = re.compile(r"(?<=[A-Za-z])_(?=[A-Za-z])")


def clean_text(text: str) -> str:
    text = SPACE_RE.sub(" ", text).strip()
    text = LETTER_UNDERSCORE_RE.sub("", text)
    text = text.replace("O_K", "OK").replace("o_k", "ok")
    text = text.replace("P_D_A", "PDA").replace("p_d_a", "pda")
    return text.strip()


def convert_one(mrt_path: Path, output_dir: Path) -> tuple[Path, int] | None:
    root = ET.parse(mrt_path).getroot()
    segments = root.findall(".//Transcript/Segment")
    if not segments:
        return None

    lines: list[str] = []
    for segment in segments:
        text = clean_text(" ".join(segment.itertext()))
        if not text:
            continue
        participant = (segment.attrib.get("Participant") or "unknown").strip()
        speaker = participant or "unknown"
        lines.append(f"[{speaker}]: {text}")

    output_path = output_dir / f"{mrt_path.stem}.txt"
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output_path, len(lines)


def main() -> None:
    if not INPUT_DIR.exists():
        raise RuntimeError(f"Input directory not found: {INPUT_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    written: list[tuple[Path, int]] = []
    skipped: list[str] = []
    for mrt_path in sorted(INPUT_DIR.glob("*.mrt")):
        result = convert_one(mrt_path, OUTPUT_DIR)
        if result is None:
            skipped.append(mrt_path.name)
            continue
        written.append(result)

    print(f"input_dir={INPUT_DIR}")
    print(f"output_dir={OUTPUT_DIR}")
    print(f"written={len(written)} skipped={len(skipped)}")
    if skipped:
        print("skipped=" + ", ".join(skipped))


if __name__ == "__main__":
    main()
