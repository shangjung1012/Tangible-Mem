from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path


REQUIRED_FILES = (
    Path("paper/lit/reference.csv"),
    Path("paper/source-notes/related-paper-notes.txt"),
    Path("paper/references.bib"),
)
BIBTEX_ENTRY_RE = re.compile(r"@[A-Za-z]+\s*\{")
BIBTEX_KEY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)")
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:arxiv(?:\.org/(?:abs|pdf)/|:)|10\.48550/arxiv\.)([A-Za-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
CITE_RE = re.compile(r"\\(?:cite|citep|citet|citeauthor|citeyear|parencite|textcite)(?:\s*\[[^\]]*\])*\s*\{([^}]+)\}")
FAKE_KEY_RE = re.compile(
    r"(todo|replace|fake|sample|example|dummy|unknown|citation[_-]?needed|tbd)",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(
    r"(TODO_REPLACE_WITH_REAL_KEY|\[citation needed\])",
    re.IGNORECASE,
)
TEXT_EXTENSIONS = {".bib", ".csv", ".md", ".tex", ".txt"}


def _is_nonempty(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _count_bibtex_entries(path: Path) -> int:
    if not path.exists():
        return 0
    return len(BIBTEX_ENTRY_RE.findall(path.read_text(encoding="utf-8", errors="replace")))


def _extract_bibtex_entries(text: str) -> list[str]:
    entries: list[str] = []
    pos = 0
    while True:
        match = BIBTEX_ENTRY_RE.search(text, pos)
        if not match:
            break
        start = match.start()
        depth = 0
        end = None
        for idx in range(match.end() - 1, len(text)):
            if text[idx] == "{":
                depth += 1
            elif text[idx] == "}":
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


def _bibtex_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    return _extract_bibtex_entries(path.read_text(encoding="utf-8", errors="replace"))


def _scan_placeholders(root: Path) -> list[str]:
    paper_dir = root / "paper"
    if not paper_dir.exists():
        return []

    findings: list[str] = []
    for path in sorted(paper_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in PLACEHOLDER_RE.finditer(line):
                findings.append(f"{rel}:{line_number}: {match.group(1)}")
    return findings


def _all_bibtex_keys(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return [match.group(1).strip() for match in BIBTEX_KEY_RE.finditer(text)]


def _scan_fake_bibtex_keys(path: Path) -> list[str]:
    return [key for key in _all_bibtex_keys(path) if FAKE_KEY_RE.search(key)]


def _duplicate_bibtex_keys(path: Path) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for key in _all_bibtex_keys(path):
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return duplicates


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


def _row_is_selected(row: list[str]) -> bool:
    return any(cell.strip().lower() == "true" for cell in row)


def _row_has_bibtex(row: list[str]) -> bool:
    return any(BIBTEX_ENTRY_RE.search(cell) for cell in row)


def _title_from_row(row: list[str]) -> str:
    for cell in row:
        value = cell.strip()
        if not value or value.lower() == "true" or BIBTEX_ENTRY_RE.search(value) or re.search(r"https?://", value, re.I):
            continue
        return re.sub(r"\s+", " ", value)
    return ""


def _selected_without_bibtex(root: Path, entries: list[str]) -> list[str]:
    csv_path = root / "paper" / "lit" / "reference.csv"
    if not csv_path.exists():
        return []
    dois, arxiv_ids, titles = _entry_coverage_sets(entries)
    unresolved: list[str] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row_number, row in enumerate(csv.reader(handle), start=1):
            if not _row_is_selected(row) or _row_has_bibtex(row):
                continue
            joined = "\n".join(row)
            row_dois = {_normalize_doi(match.group(1)) for match in DOI_RE.finditer(joined)}
            row_arxiv = {_normalize_arxiv_id(match.group(1)) for match in ARXIV_RE.finditer(joined)}
            for doi in list(row_dois):
                if "10.48550/arxiv." in doi:
                    row_arxiv.add(_normalize_arxiv_id(doi.split("arxiv.", 1)[1]))
            title = _normalize_title(_title_from_row(row))
            covered = bool(row_dois & dois) or bool(row_arxiv & arxiv_ids) or bool(title and title in titles)
            if not covered:
                unresolved.append(f"Row {row_number}: {_title_from_row(row) or '(untitled row)'}")
    return unresolved


def _strip_latex_comments(line: str) -> str:
    escaped = False
    chars: list[str] = []
    for char in line:
        if char == "%" and not escaped:
            break
        chars.append(char)
        escaped = char == "\\" and not escaped
        if char != "\\":
            escaped = False
    return "".join(chars)


def _unknown_citation_keys(root: Path, known_keys: set[str]) -> list[str]:
    tex_path = root / "paper" / "main.tex"
    if not tex_path.exists():
        return []
    unknown: list[str] = []
    for line_number, line in enumerate(tex_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        for match in CITE_RE.finditer(_strip_latex_comments(line)):
            for key in match.group(1).split(","):
                key = key.strip()
                if key and key not in known_keys:
                    unknown.append(f"paper/main.tex:{line_number}: {key}")
    return unknown


def audit_paper_sources(project_root: Path | str = ".") -> int:
    root = Path(project_root)
    missing_or_empty = [path for path in REQUIRED_FILES if not _is_nonempty(root / path)]
    references_path = root / "paper" / "references.bib"
    entries = _bibtex_entries(references_path)
    entry_count = _count_bibtex_entries(references_path)
    placeholders = _scan_placeholders(root)
    fake_keys = _scan_fake_bibtex_keys(references_path)
    duplicate_keys = _duplicate_bibtex_keys(references_path)
    selected_missing = _selected_without_bibtex(root, entries)
    unknown_cites = _unknown_citation_keys(root, set(_all_bibtex_keys(references_path)))

    print("Paper source audit")
    if missing_or_empty:
        print("Missing or empty files:")
        for path in missing_or_empty:
            print(f"- {path.as_posix()}")
    else:
        print("Missing or empty files: none")

    print(f"BibTeX entries: {entry_count}")

    if placeholders:
        print("Suspicious placeholders:")
        for finding in placeholders:
            print(f"- {finding}")
    else:
        print("Suspicious placeholders: none")

    if fake_keys:
        print("Suspicious BibTeX keys:")
        for key in fake_keys:
            print(f"- {key}")
    else:
        print("Suspicious BibTeX keys: none")

    if duplicate_keys:
        print("Duplicate BibTeX keys:")
        for key in duplicate_keys:
            print(f"- {key}")
    else:
        print("Duplicate BibTeX keys: none")

    print(f"Selected references without BibTeX: {len(selected_missing)}")
    for item in selected_missing:
        print(f"- {item}")

    if unknown_cites:
        print("Unknown citation keys:")
        for item in unknown_cites:
            print(f"- {item}")
    else:
        print("Unknown citation keys: none")

    if not references_path.exists() or entry_count == 0:
        return 1
    if missing_or_empty or duplicate_keys or unknown_cites:
        return 1
    return 0


def main() -> int:
    return audit_paper_sources(Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
