from __future__ import annotations

import csv
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CANDIDATE_COLUMNS = [
    "selected",
    "title",
    "doi_or_url",
    "bibtex",
    "source_query",
    "relevance_to_sections",
    "status",
    "notes",
]

DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
BIBTEX_START_RE = re.compile(r"@[A-Za-z]+\s*\{")


@dataclass(frozen=True)
class Seed:
    kind: str
    identifier: str
    source_query: str
    sections: str
    relevance: str
    status: str = "candidate"


@dataclass(frozen=True)
class Candidate:
    selected: str
    title: str
    doi_or_url: str
    bibtex: str
    source_query: str
    relevance_to_sections: str
    status: str
    notes: str


SEEDS: list[Seed] = [
    Seed(
        "doi",
        "10.1145/3491102.3517582",
        "inspectable AI systems; steering AI systems; transparent controllable LLM interaction",
        "3.1 Design Goals; 3.2 System Overview; 4.4 Sidecar Feedback and Human Correction Workflow",
        "LLM-chain interface work for transparency, controllability, and debugging intermediate outputs.",
    ),
    Seed(
        "doi",
        "10.1145/3491101.3519729",
        "inspectable AI systems; steering AI systems; AI workflow debugging",
        "3.1 Design Goals; 4.2 Retrieval Trace; 4.4 Sidecar Feedback and Human Correction Workflow",
        "Visual prompt-chain authoring work that foregrounds intermediate artifacts and debugging granularity.",
    ),
    Seed(
        "doi",
        "10.1145/2702123.2702509",
        "inspectable AI systems; interactive machine learning debugging",
        "4.1 Memory Representation as an Inspectable Substrate; 4.3 Memory Explorer and Topic Observatory",
        "ModelTracker supports performance analysis by making model behavior inspectable for debugging.",
    ),
    Seed(
        "doi",
        "10.1145/2858036.2858529",
        "inspectable AI systems; visual inspection of black-box machine learning",
        "4.1 Memory Representation as an Inspectable Substrate; 4.3 Memory Explorer and Topic Observatory",
        "Prospector is relevant as an interactive inspection system for model predictions and local changes.",
    ),
    Seed(
        "doi",
        "10.1145/2939672.2939778",
        "explainable AI; prediction explanation; model debugging",
        "3.1 Design Goals; 4.2 Retrieval Trace",
        "LIME is a foundational explanation method for inspecting model decisions and trust calibration.",
    ),
    Seed(
        "doi",
        "10.1016/j.artint.2018.07.007",
        "explainable AI; human-centered explanations; explanation social sciences",
        "3.1 Design Goals; 4.2 Retrieval Trace",
        "Synthesizes social-science explanation principles that can ground human-readable trace design.",
    ),
    Seed(
        "doi",
        "10.1145/1866029.1866038",
        "interactive machine learning tooling; implementation and analysis support",
        "3.2 System Overview; 4.1 Memory Representation as an Inspectable Substrate",
        "Gestalt supports the design rationale for moving between implementation artifacts and analysis views.",
    ),
    Seed(
        "doi",
        "10.1145/3290605.3300234",
        "human feedback correction AI systems; user control imperfect algorithms",
        "3.1 Design Goals; 4.4 Sidecar Feedback and Human Correction Workflow",
        "Shows how domain users can steer and refine imperfect algorithmic retrieval during use.",
    ),
    Seed(
        "doi",
        "10.1145/3530987",
        "human-centered machine learning practices; human feedback AI systems",
        "3.1 Design Goals; 5 Use Case Walkthrough",
        "Provides broader HCML practices for placing user goals and values into ML system design.",
    ),
    Seed(
        "doi",
        "10.1145/302979.303030",
        "mixed-initiative user interfaces; steering AI systems; human correction workflow",
        "3.1 Design Goals; 4.4 Sidecar Feedback and Human Correction Workflow",
        "Mixed-initiative interaction is relevant to sidecar feedback and shared-control framing.",
    ),
    Seed(
        "doi",
        "10.1145/3644815.3644945",
        "RAG debugging retrieval trace; retrieval provenance and evidence trace",
        "4.2 Retrieval Trace; 5 Use Case Walkthrough",
        "RAG failure-point analysis motivates operational trace inspection and component-level diagnosis.",
    ),
    Seed(
        "arxiv",
        "2005.11401",
        "RAG debugging retrieval trace; retrieval provenance and evidence trace",
        "3.2 System Overview; 4.2 Retrieval Trace",
        "Foundational RAG paper establishing parametric plus non-parametric memory and retrieval provenance needs.",
        "needs-review",
    ),
    Seed(
        "arxiv",
        "2309.15217",
        "RAG debugging retrieval trace; retrieval evaluation",
        "4.2 Retrieval Trace; 5 Use Case Walkthrough",
        "RAGAS provides component metrics for context relevance and answer faithfulness.",
        "needs-review",
    ),
    Seed(
        "arxiv",
        "2311.09476",
        "RAG debugging retrieval trace; retrieval evaluation; human annotations",
        "4.2 Retrieval Trace; 5 Use Case Walkthrough",
        "ARES evaluates RAG components separately and can inform trace/evidence quality checks.",
        "needs-review",
    ),
    Seed(
        "arxiv",
        "2407.11005",
        "RAG debugging retrieval trace; retrieval provenance and evidence trace",
        "4.2 Retrieval Trace; 5 Use Case Walkthrough",
        "RAGBench/TRACe is relevant to explainable and actionable RAG evaluation signals.",
        "needs-review",
    ),
]


def _request(url: str, accept: str = "application/json") -> str:
    headers = {
        "Accept": accept,
        "User-Agent": "virtual-mentor-section-345-lit/0.1 (mailto:metadata@example.invalid)",
    }
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Fetch failed for {url}: {exc}") from exc


def _normalize_title(text: str) -> str:
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\\[A-Za-z]+", "", text)
    chars = []
    for char in unicodedata.normalize("NFKC", text.casefold().replace("\n", " ")):
        category = unicodedata.category(char)
        chars.append(char if category[0] in {"L", "N"} and category != "Lm" else " ")
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def _normalize_doi(value: str) -> str:
    value = value.strip().rstrip(".,);]}\"'")
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    return value.casefold()


def _normalize_url(value: str) -> str:
    value = value.strip().rstrip(".,);]}\"'")
    value = re.sub(r"^https?://(?:www\.)?", "", value, flags=re.IGNORECASE)
    return value.casefold()


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


def _bibtex_field_value(entry: str, field: str) -> str:
    match = re.search(rf"\b{re.escape(field)}\s*=\s*", entry, re.IGNORECASE)
    if not match:
        return ""
    idx = match.end()
    while idx < len(entry) and entry[idx].isspace():
        idx += 1
    if idx >= len(entry):
        return ""
    if entry[idx] == "{":
        depth = 0
        start = idx + 1
        for pos in range(idx, len(entry)):
            if entry[pos] == "{":
                depth += 1
            elif entry[pos] == "}":
                depth -= 1
                if depth == 0:
                    return entry[start:pos]
    if entry[idx] == '"':
        start = idx + 1
        escaped = False
        for pos in range(start, len(entry)):
            if entry[pos] == '"' and not escaped:
                return entry[start:pos]
            escaped = entry[pos] == "\\" and not escaped
            if entry[pos] != "\\":
                escaped = False
    end = entry.find(",", idx)
    return entry[idx : end if end != -1 else len(entry)].strip()


def _existing_identifiers(root: Path) -> tuple[set[str], set[str], set[str]]:
    titles: set[str] = set()
    dois: set[str] = set()
    urls: set[str] = set()
    ref_path = root / "paper" / "lit" / "reference.csv"
    if ref_path.exists():
        with ref_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                for cell in row:
                    value = cell.strip()
                    if not value:
                        continue
                    if len(value) > 8 and not value.lower().startswith(("true", "false")) and not BIBTEX_START_RE.search(value):
                        titles.add(_normalize_title(value))
                    for match in DOI_RE.finditer(value):
                        dois.add(_normalize_doi(match.group(1)))
                    for match in URL_RE.finditer(value):
                        urls.add(_normalize_url(match.group(0)))
    bib_path = root / "paper" / "references.bib"
    if bib_path.exists():
        text = bib_path.read_text(encoding="utf-8", errors="replace")
        for entry in _extract_bibtex_entries(text):
            title = _bibtex_field_value(entry, "title")
            if title:
                titles.add(_normalize_title(title))
            for match in DOI_RE.finditer(entry):
                dois.add(_normalize_doi(match.group(1)))
            for match in URL_RE.finditer(entry):
                urls.add(_normalize_url(match.group(0)))
    return titles, dois, urls


def _fetch_doi_candidate(seed: Seed) -> Candidate:
    doi = _normalize_doi(seed.identifier)
    bibtex = _request(f"https://doi.org/{urllib.parse.quote(doi, safe='/')}", accept="application/x-bibtex").strip()
    entries = _extract_bibtex_entries(bibtex)
    if not entries:
        raise RuntimeError(f"DOI did not return BibTeX: {doi}")
    bibtex = entries[0]
    title = _bibtex_field_value(bibtex, "title").strip()
    if not title:
        metadata_url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
        payload = json.loads(_request(metadata_url))
        titles = payload.get("message", {}).get("title") or []
        title = str(titles[0]).strip() if titles else ""
    if not title:
        raise RuntimeError(f"Could not verify title for DOI: {doi}")
    return Candidate(
        selected="False",
        title=title,
        doi_or_url=f"https://doi.org/{doi}",
        bibtex=bibtex,
        source_query=seed.source_query,
        relevance_to_sections=seed.sections,
        status=seed.status,
        notes=seed.relevance,
    )


def _fetch_arxiv_candidate(seed: Seed) -> Candidate:
    arxiv_id = seed.identifier.strip()
    query = urllib.parse.urlencode({"id_list": arxiv_id})
    xml_text = _request(f"https://export.arxiv.org/api/query?{query}", accept="application/atom+xml")
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise RuntimeError(f"Could not verify arXiv ID: {arxiv_id}")
    title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
    if not title:
        raise RuntimeError(f"Could not verify title for arXiv ID: {arxiv_id}")
    url = f"https://arxiv.org/abs/{arxiv_id}"
    return Candidate(
        selected="False",
        title=title,
        doi_or_url=url,
        bibtex="",
        source_query=seed.source_query,
        relevance_to_sections=seed.sections,
        status=seed.status,
        notes=f"{seed.relevance} arXiv metadata verified; BibTeX intentionally left blank until manual selection/review.",
    )


def _is_duplicate(candidate: Candidate, titles: set[str], dois: set[str], urls: set[str]) -> str:
    title_key = _normalize_title(candidate.title)
    candidate_dois = {_normalize_doi(match.group(1)) for match in DOI_RE.finditer(candidate.doi_or_url + "\n" + candidate.bibtex)}
    candidate_urls = {_normalize_url(match.group(0)) for match in URL_RE.finditer(candidate.doi_or_url + "\n" + candidate.bibtex)}
    if title_key and title_key in titles:
        return "duplicate title"
    if candidate_dois & dois:
        return "duplicate DOI"
    if candidate_urls & urls:
        return "duplicate URL"
    if title_key:
        titles.add(title_key)
    dois.update(candidate_dois)
    urls.update(candidate_urls)
    return ""


def _probe_crossref(query: str) -> list[str]:
    params = urllib.parse.urlencode({"query.bibliographic": query, "rows": "3", "select": "DOI,title,score"})
    payload = json.loads(_request(f"https://api.crossref.org/works?{params}"))
    lines: list[str] = []
    for item in payload.get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        doi = item.get("DOI") or ""
        score = item.get("score") or ""
        lines.append(f"  - score={score}; DOI={doi}; title={title}")
    return lines


def _probe_arxiv(query: str) -> list[str]:
    params = urllib.parse.urlencode({"search_query": f'all:"{query}"', "start": "0", "max_results": "3"})
    xml_text = _request(f"https://export.arxiv.org/api/query?{params}", accept="application/atom+xml")
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    lines: list[str] = []
    for entry in root.findall("atom:entry", ns):
        title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
        identifier = entry.findtext("atom:id", default="", namespaces=ns)
        lines.append(f"  - {identifier}; title={title}")
    return lines


def find_candidates(project_root: Path | str = ".") -> tuple[list[Candidate], list[str]]:
    root = Path(project_root)
    titles, dois, urls = _existing_identifiers(root)
    candidates: list[Candidate] = []
    log: list[str] = [
        "# Candidate Search Log",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Acceptance policy: only DOI/arXiv seeds with verified metadata are written to candidate files. General search probes are logged but not auto-accepted.",
        "",
    ]

    for query in sorted({seed.source_query for seed in SEEDS}):
        log.append(f"## Search probe: {query}")
        try:
            log.append("Crossref:")
            log.extend(_probe_crossref(query) or ["  - no results"])
        except RuntimeError as exc:
            log.append(f"Crossref: failed: {exc}")
        time.sleep(0.2)
        try:
            log.append("arXiv:")
            log.extend(_probe_arxiv(query) or ["  - no results"])
        except RuntimeError as exc:
            log.append(f"arXiv: failed: {exc}")
        log.append("")
        time.sleep(0.2)

    log.append("## Accepted and skipped seeds")
    for seed in SEEDS:
        try:
            candidate = _fetch_doi_candidate(seed) if seed.kind == "doi" else _fetch_arxiv_candidate(seed)
            reason = _is_duplicate(candidate, titles, dois, urls)
            if reason:
                log.append(f"- skipped {seed.kind}:{seed.identifier}: {reason}; title={candidate.title}")
                continue
            candidates.append(candidate)
            log.append(f"- accepted {seed.kind}:{seed.identifier}: {candidate.title}")
        except RuntimeError as exc:
            log.append(f"- unresolved {seed.kind}:{seed.identifier}: {exc}")
        time.sleep(0.2)

    return candidates, log


def write_outputs(project_root: Path | str = ".") -> int:
    root = Path(project_root)
    candidates, log = find_candidates(root)
    csv_path = root / "paper" / "lit" / "candidate_papers.csv"
    notes_path = root / "paper" / "source-notes" / "candidate_lit_notes.md"
    log_path = root / "paper" / "lit" / "candidate_search_log.md"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS)
        writer.writeheader()
        for item in candidates:
            writer.writerow(
                {
                    "selected": item.selected,
                    "title": item.title,
                    "doi_or_url": item.doi_or_url,
                    "bibtex": item.bibtex,
                    "source_query": item.source_query,
                    "relevance_to_sections": item.relevance_to_sections,
                    "status": item.status,
                    "notes": item.notes,
                }
            )

    note_lines = [
        "# Candidate Literature Notes for Sections 3-5",
        "",
        "These notes are append-only candidates. They are not selected citations until reviewed in the literature sheet.",
        "",
    ]
    for item in candidates:
        note_lines.extend(
            [
                f"## {item.title}",
                "",
                f"- Identifier: {item.doi_or_url}",
                f"- Status: {item.status}",
                f"- Source query: {item.source_query}",
                f"- Supports: {item.relevance_to_sections}",
                f"- Why it matters: {item.notes}",
                "",
            ]
        )
    notes_path.write_text("\n".join(note_lines), encoding="utf-8")
    log_path.write_text("\n".join(log) + "\n", encoding="utf-8")

    print(f"Wrote {len(candidates)} candidate paper(s): {csv_path}")
    print(f"Wrote notes: {notes_path}")
    print(f"Wrote search log: {log_path}")
    return 0


def main() -> int:
    return write_outputs(Path.cwd())


if __name__ == "__main__":
    sys.exit(main())
