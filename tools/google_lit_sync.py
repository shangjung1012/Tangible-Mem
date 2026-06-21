from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_DOC_ID = "1UBGqLfxN_21JR8cON-spt-ZvlV8MASAE9sgzM7snJvQ"
DEFAULT_SHEET_ID = "1lfyK6up_jOVRZMAf0K7eNLCS1m1S_WuMkwvMGCagXwg"
DEFAULT_GID = "0"
DEFAULT_APPEND_COLUMNS = "A:H"
SHEET_CANDIDATE_COLUMNS = [
    "selected",
    "title",
    "doi_or_url",
    "bibtex",
    "source_query",
    "relevance_to_sections",
    "status",
    "notes",
]

BIBTEX_ENTRY_RE = re.compile(r"@[A-Za-z]+\s*\{")
BIBTEX_KEY_RE = re.compile(r"@[A-Za-z]+\s*\{\s*([^,\s]+)")
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

OAUTH_INSTRUCTIONS = (
    'gcloud auth application-default login --client-id-file="$PWD\\secrets\\google_oauth_client.json" '
    '--scopes="https://www.googleapis.com/auth/cloud-platform,'
    'https://www.googleapis.com/auth/drive.readonly,'
    'https://www.googleapis.com/auth/documents,'
    'https://www.googleapis.com/auth/spreadsheets"'
)


@dataclass(frozen=True)
class ExportResult:
    doc_bytes: int
    sheet_bytes: int
    doc_path: Path
    sheet_path: Path


@dataclass(frozen=True)
class CandidateRow:
    source_line: int
    values: list[str]
    title: str
    doi_or_url: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class AppendPlan:
    mode: str
    input_path: Path
    destination: str
    rows: list[CandidateRow]
    skipped: list[CandidateRow]


@dataclass(frozen=True)
class DocAppendPlan:
    mode: str
    input_path: Path
    destination: str
    text: str
    skipped_reason: str = ""


def _auth_headers(token: str | None = None) -> dict[str, str]:
    token = token or _adc_access_token()
    return {"Authorization": f"Bearer {token}"}


def _adc_access_token() -> str:
    executable = shutil.which("gcloud") or shutil.which("gcloud.cmd") or shutil.which("gcloud.ps1") or "gcloud"
    command = [executable, "auth", "application-default", "print-access-token"]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            "Google Application Default Credentials are not available.\n"
            f"Run:\n{OAUTH_INSTRUCTIONS}\n"
            f"{detail}"
        ) from exc
    token = result.stdout.strip()
    if not token:
        raise RuntimeError(
            "Google Application Default Credentials returned an empty token.\n"
            f"Run:\n{OAUTH_INSTRUCTIONS}"
        )
    return token


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 60,
) -> bytes:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} while calling {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error while calling {url}: {exc.reason}") from exc


def _download_url(url: str, token: str | None = None) -> bytes:
    headers = {"User-Agent": "virtual-mentor-google-lit-sync/0.2"}
    if token:
        headers.update(_auth_headers(token))
    data = _request(url, headers=headers)

    sample = data[:4096].decode("utf-8", errors="replace")
    if re.search(r"(?i)<html|ServiceLogin|accounts\.google\.com|You need access|Unauthorized", sample):
        raise RuntimeError(f"Google export returned an auth/login page instead of data: {url}")
    return data


def _doc_export_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"


def _sheet_export_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def export_sources(
    project_root: Path | str = ".",
    *,
    doc_id: str = DEFAULT_DOC_ID,
    sheet_id: str = DEFAULT_SHEET_ID,
    gid: str = DEFAULT_GID,
    downloader: Callable[[str], bytes] | None = None,
    postprocess: bool = True,
    token: str | None = None,
) -> ExportResult:
    root = Path(project_root)
    doc_path = root / "paper" / "source-notes" / "related-paper-notes.txt"
    sheet_path = root / "paper" / "lit" / "reference.csv"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)

    if downloader is None:
        token = token or _adc_access_token()

        def downloader(url: str) -> bytes:
            return _download_url(url, token)

    doc_data = downloader(_doc_export_url(doc_id))
    sheet_data = downloader(_sheet_export_url(sheet_id, gid))
    doc_path.write_bytes(doc_data)
    sheet_path.write_bytes(sheet_data)

    if postprocess:
        _run_postprocess(root)

    return ExportResult(len(doc_data), len(sheet_data), doc_path, sheet_path)


def _run_postprocess(root: Path) -> None:
    commands = [
        [sys.executable, "tools/extract_bib_from_reference_csv.py"],
        [sys.executable, "tools/fill_missing_bibtex.py"],
        [sys.executable, "tools/extract_bib_from_reference_csv.py"],
        [sys.executable, "tools/audit_paper_sources.py"],
    ]
    for command in commands:
        subprocess.run(command, cwd=root, check=True)


def _normalize_title(text: str) -> str:
    chars = [char.casefold() if char.isalnum() else " " for char in text.replace("\r", " ").replace("\n", " ")]
    return re.sub(r"\s+", " ", "".join(chars)).strip()


def _normalize_doi(doi: str) -> str:
    doi = doi.strip().rstrip(".,);]}\"'")
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.casefold()


def _normalize_url(url: str) -> str:
    value = url.strip().rstrip(".,);]}\"'")
    value = re.sub(r"^https?://(?:www\.)?", "", value, flags=re.IGNORECASE)
    return value.casefold()


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
                    if len(value) > 8 and not value.lower().startswith(("true", "false")) and not BIBTEX_ENTRY_RE.search(value):
                        titles.add(_normalize_title(value))
                    for match in DOI_RE.finditer(value):
                        dois.add(_normalize_doi(match.group(1)))
                    for match in URL_RE.finditer(value):
                        urls.add(_normalize_url(match.group(0)))

    bib_path = root / "paper" / "references.bib"
    if bib_path.exists():
        text = bib_path.read_text(encoding="utf-8", errors="replace")
        for entry in _extract_bibtex_entries(text):
            title = _normalize_title(_bibtex_field_value(entry, "title"))
            if title:
                titles.add(title)
            for match in DOI_RE.finditer(entry):
                dois.add(_normalize_doi(match.group(1)))
            for match in URL_RE.finditer(entry):
                urls.add(_normalize_url(match.group(0)))
    return titles, dois, urls


def _candidate_row_from_dict(row: dict[str, str], source_line: int) -> CandidateRow:
    values = [(row.get(column) or "").strip() for column in SHEET_CANDIDATE_COLUMNS]
    if not values[0]:
        values[0] = "False"
    if values[0].strip().lower() == "true":
        values[0] = "False"
    return CandidateRow(
        source_line=source_line,
        values=values,
        title=values[1],
        doi_or_url=values[2],
        status=values[6] or "candidate",
    )


def _load_candidate_rows(input_path: Path) -> list[CandidateRow]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []
        missing = [column for column in SHEET_CANDIDATE_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise RuntimeError(f"{input_path} is missing columns: {', '.join(missing)}")
        return [_candidate_row_from_dict(row, idx) for idx, row in enumerate(reader, start=2)]


def _filter_duplicate_candidates(root: Path, rows: Iterable[CandidateRow]) -> tuple[list[CandidateRow], list[CandidateRow]]:
    existing_titles, existing_dois, existing_urls = _existing_identifiers(root)
    kept: list[CandidateRow] = []
    skipped: list[CandidateRow] = []
    seen_titles: set[str] = set()
    seen_dois: set[str] = set()
    seen_urls: set[str] = set()

    for row in rows:
        title_key = _normalize_title(row.title)
        row_dois = {_normalize_doi(match.group(1)) for match in DOI_RE.finditer(row.doi_or_url)}
        row_urls = {_normalize_url(match.group(0)) for match in URL_RE.finditer(row.doi_or_url)}
        reason = ""
        if title_key and (title_key in existing_titles or title_key in seen_titles):
            reason = "duplicate title"
        elif row_dois and (row_dois & existing_dois or row_dois & seen_dois):
            reason = "duplicate DOI"
        elif row_urls and (row_urls & existing_urls or row_urls & seen_urls):
            reason = "duplicate URL"

        if reason:
            skipped.append(CandidateRow(row.source_line, row.values, row.title, row.doi_or_url, row.status, reason))
            continue

        kept.append(row)
        if title_key:
            seen_titles.add(title_key)
        seen_dois.update(row_dois)
        seen_urls.update(row_urls)
    return kept, skipped


def _quote_sheet_title(title: str) -> str:
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def _sheet_title_for_gid(spreadsheet_id: str, gid: str, token: str) -> str:
    fields = urllib.parse.quote("sheets.properties(sheetId,title)", safe="")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields={fields}"
    data = _request(url, headers=_auth_headers(token))
    payload = json.loads(data.decode("utf-8"))
    target_gid = int(gid)
    for sheet in payload.get("sheets", []):
        props = sheet.get("properties", {})
        if int(props.get("sheetId", -1)) == target_gid:
            return str(props.get("title", ""))
    raise RuntimeError(f"Could not find sheet gid={gid} in spreadsheet {spreadsheet_id}")


def _append_sheet_values(spreadsheet_id: str, append_range: str, values: list[list[str]], token: str) -> dict:
    encoded_range = urllib.parse.quote(append_range, safe="")
    query = urllib.parse.urlencode({"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"})
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{encoded_range}:append?{query}"
    body = json.dumps({"majorDimension": "ROWS", "values": values}, ensure_ascii=False).encode("utf-8")
    headers = {
        **_auth_headers(token),
        "Content-Type": "application/json; charset=utf-8",
    }
    data = _request(url, method="POST", headers=headers, body=body)
    return json.loads(data.decode("utf-8"))


def build_sheet_append_plan(
    project_root: Path | str,
    input_path: Path | str,
    *,
    spreadsheet_id: str = DEFAULT_SHEET_ID,
    gid: str = DEFAULT_GID,
    append_range: str | None = None,
    token: str | None = None,
    apply: bool = False,
) -> AppendPlan:
    root = Path(project_root)
    input_file = root / input_path
    if not input_file.exists():
        return AppendPlan("APPLY" if apply else "DRY RUN", input_file, "(missing input)", [], [])
    rows, skipped = _filter_duplicate_candidates(root, _load_candidate_rows(input_file))
    if append_range is None:
        if apply:
            token = token or _adc_access_token()
            sheet_title = _sheet_title_for_gid(spreadsheet_id, gid, token)
        else:
            sheet_title = f"gid:{gid}"
        append_range = f"{_quote_sheet_title(sheet_title)}!{DEFAULT_APPEND_COLUMNS}"
    return AppendPlan("APPLY" if apply else "DRY RUN", input_file, f"{spreadsheet_id} range {append_range}", rows, skipped)


def append_sheet(
    project_root: Path | str = ".",
    *,
    input_path: Path | str = Path("paper/lit/candidate_papers.csv"),
    spreadsheet_id: str = DEFAULT_SHEET_ID,
    gid: str = DEFAULT_GID,
    append_range: str | None = None,
    apply: bool = False,
    token: str | None = None,
) -> int:
    plan = build_sheet_append_plan(
        project_root,
        input_path,
        spreadsheet_id=spreadsheet_id,
        gid=gid,
        append_range=append_range,
        token=token,
        apply=apply,
    )
    _print_sheet_plan(plan)
    if not plan.rows:
        return 0
    if not apply:
        return 0
    token = token or _adc_access_token()
    destination_range = plan.destination.split(" range ", 1)[1]
    response = _append_sheet_values(spreadsheet_id, destination_range, [row.values for row in plan.rows], token)
    updated_range = response.get("updates", {}).get("updatedRange", "(unknown range)")
    print(f"APPLIED sheet append: {len(plan.rows)} row(s), updatedRange={updated_range}")
    return 0


def _print_sheet_plan(plan: AppendPlan) -> None:
    print(f"{plan.mode}: {len(plan.rows)} sheet row(s) prepared from {plan.input_path} -> {plan.destination}")
    for row in plan.rows:
        print(f"- line {row.source_line}: selected={row.values[0]}; title={row.title}; status={row.status}")
        print(f"  doi_or_url={row.doi_or_url or '(blank)'}")
    if plan.skipped:
        print(f"Skipped {len(plan.skipped)} duplicate row(s):")
        for row in plan.skipped:
            print(f"- line {row.source_line}: {row.reason}; title={row.title}")


def build_doc_append_plan(
    project_root: Path | str,
    input_path: Path | str,
    *,
    doc_id: str = DEFAULT_DOC_ID,
    apply: bool = False,
) -> DocAppendPlan:
    root = Path(project_root)
    input_file = root / input_path
    if not input_file.exists():
        return DocAppendPlan("APPLY" if apply else "DRY RUN", input_file, f"doc {doc_id}", "", "missing input")
    text = input_file.read_text(encoding="utf-8").strip()
    if not text:
        return DocAppendPlan("APPLY" if apply else "DRY RUN", input_file, f"doc {doc_id}", "", "empty input")
    notes_path = root / "paper" / "source-notes" / "related-paper-notes.txt"
    if notes_path.exists():
        existing = notes_path.read_text(encoding="utf-8", errors="replace")
        if text in existing:
            return DocAppendPlan("APPLY" if apply else "DRY RUN", input_file, f"doc {doc_id}", "", "duplicate note text")
    return DocAppendPlan("APPLY" if apply else "DRY RUN", input_file, f"doc {doc_id}", "\n\n" + text.rstrip() + "\n")


def _append_doc_text(doc_id: str, text: str, token: str) -> dict:
    url = f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate"
    body = json.dumps(
        {"requests": [{"insertText": {"endOfSegmentLocation": {}, "text": text}}]},
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        **_auth_headers(token),
        "Content-Type": "application/json; charset=utf-8",
    }
    data = _request(url, method="POST", headers=headers, body=body)
    return json.loads(data.decode("utf-8"))


def append_doc(
    project_root: Path | str = ".",
    *,
    input_path: Path | str = Path("paper/source-notes/candidate_lit_notes.md"),
    doc_id: str = DEFAULT_DOC_ID,
    apply: bool = False,
    token: str | None = None,
) -> int:
    plan = build_doc_append_plan(project_root, input_path, doc_id=doc_id, apply=apply)
    _print_doc_plan(plan)
    if not plan.text:
        return 0
    if not apply:
        return 0
    token = token or _adc_access_token()
    response = _append_doc_text(doc_id, plan.text, token)
    print(f"APPLIED doc append: {len(plan.text)} character(s), replies={len(response.get('replies', []))}")
    return 0


def _print_doc_plan(plan: DocAppendPlan) -> None:
    if plan.skipped_reason:
        print(f"{plan.mode}: 0 doc block(s) prepared from {plan.input_path} -> {plan.destination}")
        print(f"Skipped doc append: {plan.skipped_reason}")
        return
    print(f"{plan.mode}: 1 doc block prepared from {plan.input_path} -> {plan.destination}")
    print("--- doc append text begin ---")
    print(plan.text.rstrip())
    print("--- doc append text end ---")


def sync_candidates(
    project_root: Path | str = ".",
    *,
    apply: bool = False,
    spreadsheet_id: str = DEFAULT_SHEET_ID,
    doc_id: str = DEFAULT_DOC_ID,
    gid: str = DEFAULT_GID,
    sheet_input: Path | str = Path("paper/lit/candidate_papers.csv"),
    doc_input: Path | str = Path("paper/source-notes/candidate_lit_notes.md"),
) -> int:
    token = _adc_access_token() if apply else None
    sheet_status = append_sheet(
        project_root,
        input_path=sheet_input,
        spreadsheet_id=spreadsheet_id,
        gid=gid,
        apply=apply,
        token=token,
    )
    doc_status = append_doc(project_root, input_path=doc_input, doc_id=doc_id, apply=apply, token=token)
    return sheet_status or doc_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync local literature files with the Google Doc/Sheet sources.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export Google Doc/Sheet to local paper source files.")
    export_parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    export_parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    export_parser.add_argument("--gid", default=DEFAULT_GID)
    export_parser.add_argument("--no-postprocess", action="store_true")

    sheet_parser = subparsers.add_parser("append-sheet", help="Append candidate rows to the Google Sheet.")
    sheet_parser.add_argument("--input", required=True, dest="input_path")
    sheet_parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    sheet_parser.add_argument("--gid", default=DEFAULT_GID)
    sheet_parser.add_argument("--range", default=None)
    sheet_parser.add_argument("--apply", action="store_true", help="Apply write-back. Omit for dry-run.")

    doc_parser = subparsers.add_parser("append-doc", help="Append candidate notes to the Google Doc.")
    doc_parser.add_argument("--input", required=True, dest="input_path")
    doc_parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    doc_parser.add_argument("--apply", action="store_true", help="Apply write-back. Omit for dry-run.")

    sync_parser = subparsers.add_parser("sync-candidates", help="Run append-sheet and append-doc for candidate files.")
    sync_parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    sync_parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    sync_parser.add_argument("--gid", default=DEFAULT_GID)
    sync_parser.add_argument("--apply", action="store_true", help="Apply write-back. Omit for dry-run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd()
    try:
        if args.command == "export":
            result = export_sources(
                root,
                doc_id=args.doc_id,
                sheet_id=args.sheet_id,
                gid=args.gid,
                postprocess=not args.no_postprocess,
            )
            print(f"Exported Doc: {result.doc_path} ({result.doc_bytes} bytes)")
            print(f"Exported Sheet: {result.sheet_path} ({result.sheet_bytes} bytes)")
            return 0
        if args.command == "append-sheet":
            return append_sheet(
                root,
                input_path=args.input_path,
                spreadsheet_id=args.sheet_id,
                gid=args.gid,
                append_range=args.range,
                apply=args.apply,
            )
        if args.command == "append-doc":
            return append_doc(root, input_path=args.input_path, doc_id=args.doc_id, apply=args.apply)
        if args.command == "sync-candidates":
            return sync_candidates(root, apply=args.apply, spreadsheet_id=args.sheet_id, doc_id=args.doc_id, gid=args.gid)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Google literature sync failed: {exc}")
        return 1
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
