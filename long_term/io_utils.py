from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from schema import DEFAULT_TREE


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_env() -> str:
    root_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(root_env, override=True)
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Please set it in .env.")
    return api_key


def load_tree(path: Path) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(DEFAULT_TREE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in tree file: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Tree file must be a JSON object: {path}")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_json_safe(data: dict[str, Any]) -> None:
    output = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        print(output)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((output + "\n").encode("utf-8"))
