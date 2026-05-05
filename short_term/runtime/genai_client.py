from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import google.auth
from dotenv import load_dotenv
from google import genai
from google.genai import types

DEFAULT_VERTEX_LOCATION = "global"
DEFAULT_VERTEX_API_VERSION = "v1"
DEFAULT_GENAI_TIMEOUT_MS = 120_000
DEFAULT_ADC_CREDENTIALS_PATH = Path.home() / ".config/gcloud/application_default_credentials.json"
VERTEX_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
TRUTHY_VALUES = {"1", "true", "t", "yes", "y", "on"}
FALSY_VALUES = {"0", "false", "f", "no", "n", "off"}


@dataclass(frozen=True, slots=True)
class GenAIConfig:
    use_vertexai: bool
    project: str | None = None
    location: str | None = None
    api_key: str | None = None
    credentials_path: Path | None = None
    api_version: str = DEFAULT_VERTEX_API_VERSION
    timeout_ms: int = DEFAULT_GENAI_TIMEOUT_MS


def load_dotenv_files() -> None:
    root_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(root_env, override=True)
    load_dotenv(override=True)


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in TRUTHY_VALUES:
        return True
    if raw_value in FALSY_VALUES:
        return False
    raise RuntimeError(
        f"{name} must be one of true/false, 1/0, yes/no, or on/off; got {raw_value!r}."
    )


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer; got {raw_value!r}.") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}; got {value}.")
    return value


def _gcloud_config_project() -> str:
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""
    project = result.stdout.strip()
    if project == "(unset)":
        return ""
    return project


def _vertex_credentials_path() -> Path:
    raw_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return DEFAULT_ADC_CREDENTIALS_PATH


def load_genai_config(api_key: str | None = None) -> GenAIConfig:
    load_dotenv_files()

    use_vertexai = _env_bool("GOOGLE_GENAI_USE_VERTEXAI", default=True)
    api_version = (
        os.getenv("GOOGLE_GENAI_API_VERSION", "").strip()
        or DEFAULT_VERTEX_API_VERSION
    )
    timeout_ms = _env_int("GOOGLE_GENAI_TIMEOUT_MS", DEFAULT_GENAI_TIMEOUT_MS)

    if use_vertexai:
        credentials_path = _vertex_credentials_path()
        if not credentials_path.exists():
            raise RuntimeError(
                "Vertex AI is enabled, but the credentials JSON was not found: "
                f"{credentials_path}. Set GOOGLE_APPLICATION_CREDENTIALS to a valid "
                "credentials file or run `gcloud auth application-default login`."
            )
        project = (
            os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
            or os.getenv("GCLOUD_PROJECT", "").strip()
            or os.getenv("GCP_PROJECT", "").strip()
            or _gcloud_config_project()
        )
        location = (
            os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
            or os.getenv("GOOGLE_CLOUD_REGION", "").strip()
            or os.getenv("VERTEX_AI_LOCATION", "").strip()
            or DEFAULT_VERTEX_LOCATION
        )
        if not project:
            raise RuntimeError(
                "Vertex AI is enabled, but no Google Cloud project was found. "
                "Set GOOGLE_CLOUD_PROJECT in .env or run `gcloud config set project PROJECT_ID`."
            )
        return GenAIConfig(
            use_vertexai=True,
            project=project,
            location=location,
            credentials_path=credentials_path,
            api_version=api_version,
            timeout_ms=timeout_ms,
        )

    resolved_api_key = (
        (api_key or "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
        or os.getenv("GEMINI_API_KEY", "").strip()
    )
    if not resolved_api_key:
        raise RuntimeError(
            "Gemini Developer API is enabled, but no API key was found. "
            "Set GOOGLE_API_KEY or GEMINI_API_KEY in .env, or set "
            "GOOGLE_GENAI_USE_VERTEXAI=true to use Vertex AI with ADC."
        )
    return GenAIConfig(
        use_vertexai=False,
        api_key=resolved_api_key,
        api_version=api_version,
        timeout_ms=timeout_ms,
    )


def create_genai_client(config: GenAIConfig | None = None) -> genai.Client:
    resolved = config or load_genai_config()
    if resolved.use_vertexai:
        if resolved.credentials_path is None:
            raise RuntimeError("Vertex AI credentials_path is missing.")
        credentials, _ = google.auth.load_credentials_from_file(
            str(resolved.credentials_path),
            scopes=VERTEX_SCOPES,
        )
        return genai.Client(
            vertexai=True,
            credentials=credentials,
            project=resolved.project,
            location=resolved.location,
            http_options=types.HttpOptions(
                apiVersion=resolved.api_version,
                timeout=resolved.timeout_ms,
            ),
        )
    return genai.Client(
        api_key=resolved.api_key,
        http_options=types.HttpOptions(
            apiVersion=resolved.api_version,
            timeout=resolved.timeout_ms,
        ),
    )


def describe_genai_config(config: GenAIConfig) -> str:
    if config.use_vertexai:
        return (
            "Vertex AI "
            f"project={config.project} location={config.location} "
            f"api_version={config.api_version} "
            f"timeout_ms={config.timeout_ms} "
            f"credentials={config.credentials_path}"
        )
    return f"Gemini Developer API api_version={config.api_version} timeout_ms={config.timeout_ms}"
