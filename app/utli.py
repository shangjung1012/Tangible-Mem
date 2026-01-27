from config import ROOT


def record(role: str, text: str, file: str):
    with open(ROOT / "record" / file, "a+", encoding="utf-8") as f:
        f.write(f'{role}:\n{text}\n\n\n')