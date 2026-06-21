from __future__ import annotations

import csv
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path


BIBTEX_START_RE = re.compile(r"@[A-Za-z]+\s*\{")
BIBTEX_KEY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)")
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:arxiv(?:\.org/(?:abs|pdf)/|:)|10\.48550/arxiv\.)([A-Za-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractionResult:
    selected_row_count: int
    entry_count: int
    missing_bibtex_count: int
    references_path: Path
    missing_todo_path: Path


def _row_is_selected(row: list[str]) -> bool:
    return any(cell.strip().lower() == "true" for cell in row)


def _extract_bibtex_entries(text: str) -> list[str]:
    entries: list[str] = []
    pos = 0
    while True:
        match = BIBTEX_START_RE.search(text, pos)
        if not match:
            break

        start = match.start()
        depth = 0
        end = None
        for idx in range(match.end() - 1, len(text)):
            char = text[idx]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break

        if end is None:
            pos = match.end()
            continue

        entries.append(text[start:end].strip())
        pos = end
    return entries


def _entry_key(entry: str) -> str:
    match = BIBTEX_KEY_RE.search(entry)
    if match:
        return match.group(1).strip()
    return entry.strip()


def _normalize_doi(doi: str) -> str:
    doi = doi.strip().rstrip(".,);]}\"'")
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.casefold()


def _normalize_arxiv_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    item = arxiv_id.strip().rstrip(".,);]")
    item = re.sub(r"^arxiv:", "", item, flags=re.IGNORECASE)
    item = re.sub(r"v\d+$", "", item, flags=re.IGNORECASE)
    return item.casefold()


def _normalize_title(text: str) -> str:
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\\[A-Za-z]+", "", text)
    text = text.replace("\r", " ").replace("\n", " ")
    chars = []
    for char in unicodedata.normalize("NFKC", text.casefold()):
        category = unicodedata.category(char)
        chars.append(char if category[0] in {"L", "N"} and category != "Lm" else " ")
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def _entry_title(entry: str) -> str:
    return _normalize_title(_bibtex_field_value(entry, "title"))


def _bibtex_field_value(entry: str, field: str) -> str:
    match = re.search(rf"\b{re.escape(field)}\s*=\s*", entry, re.IGNORECASE)
    if not match:
        return ""
    idx = match.end()
    while idx < len(entry) and entry[idx].isspace():
        idx += 1
    if idx >= len(entry):
        return ""
    delimiter = entry[idx]
    if delimiter == "{":
        depth = 0
        start = idx + 1
        for pos in range(idx, len(entry)):
            if entry[pos] == "{":
                depth += 1
            elif entry[pos] == "}":
                depth -= 1
                if depth == 0:
                    return entry[start:pos]
    if delimiter == '"':
        start = idx + 1
        escaped = False
        for pos in range(start, len(entry)):
            if entry[pos] == '"' and not escaped:
                return entry[start:pos]
            escaped = entry[pos] == "\\" and not escaped
            if entry[pos] != "\\":
                escaped = False
    start = idx
    end = entry.find(",", start)
    return entry[start:end if end != -1 else len(entry)].strip()


def _entry_arxiv_ids(entry: str) -> set[str]:
    ids = {_normalize_arxiv_id(match.group(1)) for match in ARXIV_RE.finditer(entry)}
    eprint_match = re.search(r"eprint\s*=\s*[\{\"]([^}\"]+)", entry, re.IGNORECASE)
    if eprint_match:
        ids.add(_normalize_arxiv_id(eprint_match.group(1)))
    return {item for item in ids if item}


def _entry_coverage_sets(entries: list[str]) -> tuple[set[str], set[str], set[str]]:
    dois: set[str] = set()
    arxiv_ids: set[str] = set()
    titles: set[str] = set()
    for entry in entries:
        dois.update(_normalize_doi(match.group(1)) for match in DOI_RE.finditer(entry))
        arxiv_ids.update(_entry_arxiv_ids(entry))
        title = _entry_title(entry)
        if title:
            titles.add(title)
    return dois, arxiv_ids, titles


def _title_from_row(row: list[str]) -> str:
    for cell in row:
        value = cell.strip()
        if not value or value.lower() == "true" or BIBTEX_START_RE.search(value) or re.search(r"https?://", value, re.I):
            continue
        return re.sub(r"\s+", " ", value)
    return ""


def _row_is_covered_by_entries(row: list[str], entries: dict[str, str]) -> bool:
    if not entries:
        return False
    dois, arxiv_ids, titles = _entry_coverage_sets(list(entries.values()))
    joined = "\n".join(row)
    row_dois = {_normalize_doi(match.group(1)) for match in DOI_RE.finditer(joined)}
    row_arxiv = {_normalize_arxiv_id(match.group(1)) for match in ARXIV_RE.finditer(joined)}
    for doi in list(row_dois):
        if "10.48550/arxiv." in doi:
            row_arxiv.add(_normalize_arxiv_id(doi.split("arxiv.", 1)[1]))
    row_title = _normalize_title(_title_from_row(row))
    return bool(row_dois & dois) or bool(row_arxiv & arxiv_ids) or bool(row_title and row_title in titles)


def _entry_signature(entry: str) -> str:
    dois, arxiv_ids, _titles = _entry_coverage_sets([entry])
    if dois:
        return "doi:" + sorted(dois)[0]
    if arxiv_ids:
        return "arxiv:" + sorted(arxiv_ids)[0]
    title = _entry_title(entry)
    if title:
        return "title:" + title
    return ""


def _add_entry(entries_by_key: dict[str, str], signatures: set[str], entry: str) -> None:
    signature = _entry_signature(entry)
    if signature and signature in signatures:
        return
    if signature:
        signatures.add(signature)
    entries_by_key.setdefault(_entry_key(entry), entry)


def _looks_like_header(row: list[str]) -> bool:
    joined = ",".join(cell.strip().lower() for cell in row)
    return not _row_is_selected(row) and "bib" in joined


def _describe_missing_row(row_number: int, row: list[str], header: list[str]) -> str:
    lowered_header = [cell.strip().lower() for cell in header]
    for candidate in ("title", "paper", "reference", "name"):
        if candidate in lowered_header:
            value = row[lowered_header.index(candidate)].strip()
            if value:
                return f"Row {row_number}: {value}"

    for cell in row:
        value = cell.strip()
        if value and value.lower() != "true" and not BIBTEX_START_RE.search(value):
            return f"Row {row_number}: {value}"
    return f"Row {row_number}"


def extract_bib_from_reference_csv(project_root: Path | str = ".") -> ExtractionResult:
    root = Path(project_root)
    csv_path = root / "paper" / "lit" / "reference.csv"
    references_path = root / "paper" / "references.bib"
    missing_todo_path = root / "paper" / "lit" / "missing_bibtex_todo.md"

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing required CSV: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    header: list[str] = []
    data_rows = rows
    first_row_number = 1
    if rows and _looks_like_header(rows[0]):
        header = rows[0]
        data_rows = rows[1:]
        first_row_number = 2

    selected_count = 0
    missing_rows: list[str] = []
    entries_by_key: dict[str, str] = {}
    entry_signatures: set[str] = set()

    if references_path.exists():
        for entry in _extract_bibtex_entries(references_path.read_text(encoding="utf-8", errors="replace")):
            _add_entry(entries_by_key, entry_signatures, entry)

    for offset, row in enumerate(data_rows):
        row_number = first_row_number + offset
        if not _row_is_selected(row):
            continue
        selected_count += 1
        row_entries: list[str] = []
        for cell in row:
            row_entries.extend(_extract_bibtex_entries(cell))
        if not row_entries:
            if not _row_is_covered_by_entries(row, entries_by_key):
                missing_rows.append(_describe_missing_row(row_number, row, header))
            continue
        for entry in row_entries:
            _add_entry(entries_by_key, entry_signatures, entry)

    references_path.parent.mkdir(parents=True, exist_ok=True)
    missing_todo_path.parent.mkdir(parents=True, exist_ok=True)

    references_text = "\n\n".join(entries_by_key.values())
    if references_text:
        references_text += "\n"
    references_path.write_text(references_text, encoding="utf-8")

    if missing_rows:
        todo_lines = [
            "# Missing BibTeX TODO",
            "",
            "The selected rows below do not contain a BibTeX entry. Add verified BibTeX manually; do not invent entries.",
            "",
        ]
        todo_lines.extend(f"- {row}" for row in missing_rows)
        todo_lines.append("")
    else:
        todo_lines = [
            "# Missing BibTeX TODO",
            "",
            "No selected rows are missing BibTeX.",
            "",
        ]
    missing_todo_path.write_text("\n".join(todo_lines), encoding="utf-8")

    return ExtractionResult(
        selected_row_count=selected_count,
        entry_count=len(entries_by_key),
        missing_bibtex_count=len(missing_rows),
        references_path=references_path,
        missing_todo_path=missing_todo_path,
    )


def main() -> int:
    try:
        result = extract_bib_from_reference_csv(Path.cwd())
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    print(f"Selected references: {result.selected_row_count}")
    print(f"Extracted BibTeX entries: {result.entry_count}")
    print(f"Selected references missing BibTeX: {result.missing_bibtex_count}")
    print(f"Wrote: {result.references_path}")
    print(f"Wrote: {result.missing_todo_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
