from __future__ import annotations

import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from schema import DEFAULT_TREE

API_KEY_SPLIT_RE = re.compile(r"[\s,;]+")
_ENV_LOADED = False


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_env_loaded() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    root_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(root_env, override=True)
    load_dotenv(override=True)
    _ENV_LOADED = True


def is_vertex_ai_enabled(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get("GOOGLE_GENAI_USE_VERTEXAI", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def parse_gemini_api_keys_from_env(env: dict[str, str] | None = None) -> list[str]:
    """Return configured GenAI API keys in call order, preserving compatibility."""
    source = env if env is not None else os.environ

    def _dedupe(values: list[str]) -> list[str]:
        output: list[str] = []
        for key in values:
            key = key.strip()
            if key and key not in output:
                output.append(key)
        return output

    multi_keys = _dedupe(
        API_KEY_SPLIT_RE.split(
            source.get("GOOGLE_API_KEYS", "") or source.get("GEMINI_API_KEYS", "")
        )
    )
    if multi_keys:
        return multi_keys

    numbered_keys = _dedupe(
        [
            source.get(f"GOOGLE_API_KEY_{i}", "")
            or source.get(f"GOOGLE_API_KEY{i}", "")
            or source.get(f"GEMINI_API_KEY_{i}", "")
            or source.get(f"GEMINI_API_KEY{i}", "")
            for i in range(1, 10)
        ]
    )
    if numbered_keys:
        return numbered_keys

    single_key = (
        source.get("GOOGLE_API_KEY", "") or source.get("GEMINI_API_KEY", "")
    ).strip()
    return [single_key] if single_key else []


def load_api_keys() -> list[str]:
    ensure_env_loaded()
    api_keys = parse_gemini_api_keys_from_env()
    if not api_keys:
        if is_vertex_ai_enabled():
            return []
        raise RuntimeError(
            "GenAI credentials are missing. Either enable Vertex AI with "
            "GOOGLE_GENAI_USE_VERTEXAI=true and configure GOOGLE_CLOUD_PROJECT / "
            "GOOGLE_APPLICATION_CREDENTIALS (or GOOGLE_API_KEY), or set "
            "GEMINI_API_KEY / GEMINI_API_KEYS / GEMINI_API_KEY_1...9 in .env."
        )
    return api_keys


def load_env() -> str:
    """Backward-compatible helper for callers that only need one API key."""
    api_keys = load_api_keys()
    return api_keys[0] if api_keys else ""


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
