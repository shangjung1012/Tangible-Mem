from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_observatory.services.scoring_export import export_observatory_run_to_scoring_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Memory Observatory run to the answer scoring CSV schema.")
    parser.add_argument("--run", required=True, help="Path to memory_observatory/runs/<run_id>.")
    parser.add_argument("--out", required=True, help="Output CSV path.")
    args = parser.parse_args(argv)

    summary = export_observatory_run_to_scoring_csv(Path(args.run), Path(args.out))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
