# Import Literature Sources from Google

PowerShell/terminal cannot access the Google Doc/Sheet because it does not have browser login cookies.

Please manually export:

1. Google Doc:
   File -> Download -> Plain text (.txt)
   Save as:
   `paper/source-notes/related-paper-notes.txt`

2. Google Sheet:
   File -> Download -> Comma-separated values (.csv)
   Save as:
   `paper/lit/reference.csv`

After both files exist, run:

```powershell
python tools/extract_bib_from_reference_csv.py
python tools/audit_paper_sources.py
```
