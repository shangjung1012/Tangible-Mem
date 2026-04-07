from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def record(role: str, text: str, file: str):
    record_dir = ROOT / "record"
    record_dir.mkdir(parents=True, exist_ok=True)
    with open(record_dir / file, "a+", encoding="utf-8") as f:
        f.write(f'{role}:\n{text}\n\n\n')
