from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


BIBTEX_START_RE = re.compile(r"@[A-Za-z]+\s*\{")
BIBTEX_KEY_RE = re.compile(r"(@[A-Za-z]+\s*\{\s*)([^,\s]+)")
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
ARXIV_RE = re.compile(
    r"(?:arxiv(?:\.org/(?:abs|pdf)/|:)|10\.48550/arxiv\.)([A-Za-z\-]+/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://", re.IGNORECASE)


@dataclass(frozen=True)
class CrossrefCandidate:
    title: str
    doi: str
    score: float
    bibtex: str | None = None


@dataclass(frozen=True)
class FillResult:
    before_count: int
    added_count: int
    after_count: int
    unresolved_count: int
    ambiguous_count: int


@dataclass(frozen=True)
class SelectedReference:
    row_number: int
    title: str
    doi: str | None
    arxiv_id: str | None
    cells: list[str]


class BibtexFetcher(Protocol):
    def fetch_bibtex_for_doi(self, doi: str) -> str | None: ...

    def fetch_bibtex_for_arxiv(self, arxiv_id: str) -> str | None: ...

    def query_crossref_by_title(self, title: str) -> list[CrossrefCandidate]: ...


class NetworkBibtexFetcher:
    user_agent = "virtual-mentor-citation-workflow/0.1 (mailto:metadata@example.invalid)"

    def fetch_bibtex_for_doi(self, doi: str) -> str | None:
        quoted_doi = urllib.parse.quote(doi.strip(), safe="/")
        request = urllib.request.Request(
            f"https://doi.org/{quoted_doi}",
            headers={
                "Accept": "application/x-bibtex",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                text = response.read().decode("utf-8", errors="replace").strip()
        except (urllib.error.URLError, TimeoutError):
            return None
        if _extract_bibtex_entries(text):
            return text
        return None

    def fetch_bibtex_for_arxiv(self, arxiv_id: str) -> str | None:
        query = urllib.parse.urlencode({"id_list": arxiv_id.strip()})
        request = urllib.request.Request(
            f"https://export.arxiv.org/api/query?{query}",
            headers={"User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                xml_text = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError):
            return None
        return _bibtex_from_arxiv_atom(arxiv_id, xml_text)

    def query_crossref_by_title(self, title: str) -> list[CrossrefCandidate]:
        params = urllib.parse.urlencode(
            {
                "query.bibliographic": title,
                "rows": "3",
                "select": "DOI,title,score",
            }
        )
        request = urllib.request.Request(
            f"https://api.crossref.org/works?{params}",
            headers={"User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return []

        candidates: list[CrossrefCandidate] = []
        for item in payload.get("message", {}).get("items", []):
            doi = str(item.get("DOI") or "").strip()
            titles = item.get("title") or []
            candidate_title = str(titles[0]).strip() if titles else ""
            score = float(item.get("score") or 0.0)
            if not doi or not candidate_title:
                continue
            bibtex = self.fetch_bibtex_for_doi(doi)
            candidates.append(CrossrefCandidate(candidate_title, doi, score, bibtex))
        return candidates


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


def _entry_key(entry: str) -> str:
    match = BIBTEX_KEY_RE.search(entry)
    return match.group(2).strip() if match else entry.strip()


def _entry_dois(entry: str) -> set[str]:
    return {_normalize_doi(match.group(1)) for match in DOI_RE.finditer(entry)}


def _entry_arxiv_ids(entry: str) -> set[str]:
    ids = {_normalize_arxiv_id(match.group(1)) for match in ARXIV_RE.finditer(entry)}
    eprint_match = re.search(r"eprint\s*=\s*[\{\"]([^}\"]+)", entry, re.IGNORECASE)
    if eprint_match:
        ids.add(_normalize_arxiv_id(eprint_match.group(1)))
    return {item for item in ids if item}


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


def _normalize_title(text: str) -> str:
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\\[A-Za-z]+", "", text)
    text = text.replace("\r", " ").replace("\n", " ")
    chars = []
    for char in unicodedata.normalize("NFKC", text.casefold()):
        category = unicodedata.category(char)
        chars.append(char if category[0] in {"L", "N"} and category != "Lm" else " ")
    return re.sub(r"\s+", " ", "".join(chars)).strip()


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


def _extract_doi(text: str) -> str | None:
    match = DOI_RE.search(text)
    if not match:
        return None
    return _normalize_doi(match.group(1))


def _extract_arxiv_id(text: str) -> str | None:
    match = ARXIV_RE.search(text)
    if match:
        return _normalize_arxiv_id(match.group(1))
    return None


def _title_from_row(row: list[str]) -> str:
    for cell in row:
        value = cell.strip()
        if not value or value.lower() == "true" or BIBTEX_START_RE.search(value) or URL_RE.search(value):
            continue
        return re.sub(r"\s+", " ", value)
    return ""


def _selected_missing_rows(csv_path: Path) -> list[SelectedReference]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    selected: list[SelectedReference] = []
    for row_number, row in enumerate(rows, start=1):
        if not _row_is_selected(row):
            continue
        if any(_extract_bibtex_entries(cell) for cell in row):
            continue
        joined = "\n".join(row)
        doi = _extract_doi(joined)
        arxiv_id = _extract_arxiv_id(joined)
        if doi and "10.48550/arxiv." in doi:
            arxiv_id = _normalize_arxiv_id(doi.split("arxiv.", 1)[1])
        selected.append(SelectedReference(row_number, _title_from_row(row), doi, arxiv_id, row))
    return selected


def _load_existing_entries(references_path: Path) -> dict[str, str]:
    if not references_path.exists():
        return {}
    text = references_path.read_text(encoding="utf-8", errors="replace")
    entries: dict[str, str] = {}
    signatures: set[str] = set()
    for entry in _extract_bibtex_entries(text):
        signature = _entry_signature(entry)
        if signature and signature in signatures:
            continue
        if signature:
            signatures.add(signature)
        entries.setdefault(_entry_key(entry), entry)
    return entries


def _entry_signature(entry: str) -> str:
    dois = sorted(_entry_dois(entry))
    if dois:
        return "doi:" + dois[0]
    arxiv_ids = sorted(_entry_arxiv_ids(entry))
    if arxiv_ids:
        return "arxiv:" + arxiv_ids[0]
    title = _entry_title(entry)
    if title:
        return "title:" + title
    return ""


def _covered_by_existing(ref: SelectedReference, entries: dict[str, str]) -> bool:
    if not entries:
        return False
    entry_text = "\n\n".join(entries.values())
    if ref.doi and ref.doi in {_normalize_doi(match.group(1)) for match in DOI_RE.finditer(entry_text)}:
        return True
    if ref.arxiv_id:
        arxiv_ids: set[str] = set()
        for entry in entries.values():
            arxiv_ids.update(_entry_arxiv_ids(entry))
        if ref.arxiv_id in arxiv_ids:
            return True
    normalized_title = _normalize_title(ref.title)
    if normalized_title:
        return any(_entry_title(entry) == normalized_title for entry in entries.values())
    return False


def _rename_bibtex_key(entry: str, existing_keys: set[str]) -> str:
    key = _entry_key(entry)
    if key not in existing_keys:
        return entry
    suffix = 2
    while f"{key}-{suffix}" in existing_keys:
        suffix += 1
    return BIBTEX_KEY_RE.sub(rf"\g<1>{key}-{suffix}", entry, count=1)


def _is_high_confidence_crossref_match(title: str, candidate: CrossrefCandidate) -> bool:
    return (
        bool(candidate.bibtex)
        and candidate.score >= 30.0
        and _normalize_title(title) == _normalize_title(candidate.title)
    )


def _bibtex_from_arxiv_atom(arxiv_id: str, xml_text: str) -> str | None:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None
    title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
    published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
    summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
    category = entry.find("arxiv:primary_category", ns)
    primary_class = category.attrib.get("term", "") if category is not None else ""
    authors = [
        (author.findtext("atom:name", default="", namespaces=ns) or "").strip()
        for author in entry.findall("atom:author", ns)
    ]
    authors = [author for author in authors if author]
    year = published[:4] if published else ""
    normalized_id = _normalize_arxiv_id(arxiv_id) or arxiv_id
    key = "arxiv" + re.sub(r"[^A-Za-z0-9]+", "", normalized_id)
    if not title or not authors or not year:
        return None
    lines = [
        f"@misc{{{key},",
        f"  title={{{title}}},",
        f"  author={{{' and '.join(authors)}}},",
        f"  year={{{year}}},",
        f"  eprint={{{normalized_id}}},",
        "  archivePrefix={arXiv},",
    ]
    if primary_class:
        lines.append(f"  primaryClass={{{primary_class}}},")
    lines.append(f"  url={{https://arxiv.org/abs/{normalized_id}}},")
    if summary:
        lines.append(f"  abstract={{{re.sub(r'\\s+', ' ', summary)}}},")
    lines.append("}")
    return "\n".join(lines)


def _write_missing_todo(path: Path, unresolved: list[SelectedReference]) -> None:
    lines = [
        "# Missing BibTeX TODO",
        "",
        "The selected rows below still do not have a high-confidence BibTeX entry. Add verified BibTeX manually; do not invent entries.",
        "",
    ]
    if unresolved:
        lines.extend(f"- Row {ref.row_number}: {ref.title or '(untitled row)'}" for ref in unresolved)
    else:
        lines.append("No selected rows are missing BibTeX.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_manual_review(path: Path, ambiguous: list[tuple[SelectedReference, list[CrossrefCandidate]]]) -> None:
    lines = [
        "# BibTeX Needs Manual Review",
        "",
        "These selected references had possible metadata matches, but the script did not auto-accept them.",
        "",
    ]
    if not ambiguous:
        lines.append("No ambiguous matches.")
    for ref, candidates in ambiguous:
        lines.append(f"## Row {ref.row_number}: {ref.title or '(untitled row)'}")
        lines.append("")
        for candidate in candidates:
            lines.append(f"- score={candidate.score:.2f}; DOI={candidate.doi}; title={candidate.title}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def fill_missing_bibtex(project_root: Path | str = ".", fetcher: BibtexFetcher | None = None) -> FillResult:
    root = Path(project_root)
    csv_path = root / "paper" / "lit" / "reference.csv"
    references_path = root / "paper" / "references.bib"
    missing_todo_path = root / "paper" / "lit" / "missing_bibtex_todo.md"
    manual_review_path = root / "paper" / "lit" / "bibtex_needs_manual_review.md"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing required CSV: {csv_path}")

    active_fetcher = fetcher or NetworkBibtexFetcher()
    entries = _load_existing_entries(references_path)
    before_count = len(entries)
    existing_keys = set(entries)
    unresolved: list[SelectedReference] = []
    ambiguous: list[tuple[SelectedReference, list[CrossrefCandidate]]] = []
    added_entries: list[str] = []

    for ref in _selected_missing_rows(csv_path):
        if _covered_by_existing(ref, entries):
            continue
        bibtex: str | None = None
        if ref.arxiv_id:
            bibtex = active_fetcher.fetch_bibtex_for_arxiv(ref.arxiv_id)
        if not bibtex and ref.doi:
            bibtex = active_fetcher.fetch_bibtex_for_doi(ref.doi)
        if not bibtex and ref.title:
            candidates = active_fetcher.query_crossref_by_title(ref.title)
            high_confidence = [candidate for candidate in candidates if _is_high_confidence_crossref_match(ref.title, candidate)]
            if high_confidence:
                bibtex = high_confidence[0].bibtex
            elif candidates:
                ambiguous.append((ref, candidates))

        if not bibtex or not _extract_bibtex_entries(bibtex):
            unresolved.append(ref)
            continue

        for entry in _extract_bibtex_entries(bibtex):
            signature = _entry_signature(entry)
            if signature and signature in {_entry_signature(existing) for existing in entries.values()}:
                continue
            renamed = _rename_bibtex_key(entry, existing_keys)
            key = _entry_key(renamed)
            existing_keys.add(key)
            entries[key] = renamed
            added_entries.append(renamed)

    references_path.parent.mkdir(parents=True, exist_ok=True)
    references_text = "\n\n".join(entries.values())
    if references_text:
        references_text += "\n"
    references_path.write_text(references_text, encoding="utf-8")
    _write_missing_todo(missing_todo_path, unresolved)
    _write_manual_review(manual_review_path, ambiguous)

    return FillResult(
        before_count=before_count,
        added_count=len(added_entries),
        after_count=len(entries),
        unresolved_count=len(unresolved),
        ambiguous_count=len(ambiguous),
    )


def main() -> int:
    try:
        result = fill_missing_bibtex(Path.cwd())
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    print(f"BibTeX entries before: {result.before_count}")
    print(f"BibTeX entries added: {result.added_count}")
    print(f"BibTeX entries after: {result.after_count}")
    print(f"Still missing: {result.unresolved_count}")
    print(f"Ambiguous for manual review: {result.ambiguous_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
