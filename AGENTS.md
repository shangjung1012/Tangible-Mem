# AGENTS.md

## Project goal

Turn the Virtual Mentor / layered memory project into a CHI/HCI-style paper.

## Paper writing rules

- Target style: ACM CHI / HCI research paper.
- Use Traditional Chinese with Taiwan wording when drafting Chinese text.
- Do not fabricate citations, BibTeX keys, DOI, author names, years, venues, abstracts, statistics, or user-study results.
- Final LaTeX citations must use real keys from `paper/references.bib`.
- New literature search is allowed when existing sources are insufficient. Prefer ACM DL, arXiv, ACL Anthology, Crossref, DOI.org, and use Semantic Scholar only as discovery.
- New papers must go through the candidate workflow before they can be cited: add rows to `paper/lit/candidate_papers.csv`, add notes to `paper/source-notes/candidate_lit_notes.md`, sync only through `tools/google_lit_sync.py`, dry-run before any `--apply`, and keep Google writes append-only.
- Do not cite unverified candidate papers in final prose. If evidence is missing, mark `[citation needed]`.
- Before drafting Introduction, Related Work, or Discussion, create/update `paper/claim_evidence_matrix.md`.
- Prefer CHI, CSCW, UIST, IUI, TOCHI, PACMHCI, DIS, UbiComp/IMWUT, and relevant IR/NLP/RAG literature.
- Separate:
  - claims supported by literature
  - claims supported by our system/evaluation
  - speculation or design implications
- Update `paper/claim_evidence_matrix.md` whenever claim support changes.

## Literature source files

- `paper/lit/reference.csv` is the exported literature inventory from our Google Sheet.
- `paper/references.bib` is the only allowed BibTeX source for LaTeX citations.
- `paper/source-notes/related-paper-notes.txt` contains human-written reading notes exported from our Google Doc.
- Use source notes to understand relevance and claims, but cite papers through BibTeX keys in `paper/references.bib`.
- Do not cite Google Docs or Google Sheets as academic references.
- If a verified paper lacks BibTeX, fetch/add it to `paper/references.bib`, then run the source audit before citing it.

## CHI / ACM format notes

- Use ACM Primary Article Template / acmart.
- For review-style draft, prefer `\documentclass[manuscript,review,anonymous]{acmart}` unless the venue/class requires otherwise.
- Keep `references.bib` clean and compile regularly.
