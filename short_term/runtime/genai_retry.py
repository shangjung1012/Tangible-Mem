from __future__ import annotations

import os
import queue
import random
import threading
import time
from typing import Any, Callable

from google.genai import errors

MAX_API_RETRIES = 15
API_RETRY_BASE_DELAY_SECONDS = 2.0
API_RETRY_MAX_DELAY_SECONDS = 20.0
API_RETRY_JITTER_SECONDS = 1.0
DEFAULT_CALL_TIMEOUT_SECONDS = 180.0
MAX_TIMEOUT_RETRIES = 2


def _is_retryable_genai_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        code = getattr(exc, "code", None)
        status = str(getattr(exc, "status", "") or "").upper()
        return code == 429 or status == "RESOURCE_EXHAUSTED"

    message = str(exc).upper()
    return (
        "429" in message
        or "RESOURCE_EXHAUSTED" in message
        or "503" in message
        or "UNAVAILABLE" in message
    )


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    if not retry_after:
        return None

    try:
        return max(float(retry_after), 0.0)
    except ValueError:
        return None


def _retry_delay_seconds(exc: Exception, attempt: int) -> float:
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return min(retry_after, API_RETRY_MAX_DELAY_SECONDS)
    exponential_delay = min(
        API_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
        API_RETRY_MAX_DELAY_SECONDS,
    )
    return exponential_delay + random.uniform(0, API_RETRY_JITTER_SECONDS)


def call_with_retry(
    func: Callable[[], Any],
    *,
    log: Callable[[str], None] | None = None,
    on_retry: Callable[[dict[str, Any]], None] | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
    operation_name: str,
    max_retries: int = MAX_API_RETRIES,
) -> Any:
    timeout_seconds = _call_timeout_seconds()
    for attempt in range(1, max_retries + 1):
        try:
            return _call_with_timeout(
                func,
                operation_name=operation_name,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            effective_max_retries = (
                min(max_retries, MAX_TIMEOUT_RETRIES)
                if isinstance(exc, TimeoutError)
                else max_retries
            )
            if not _is_retryable_genai_error(exc) or attempt >= effective_max_retries:
                raise

            delay_seconds = _retry_delay_seconds(exc, attempt)
            if on_retry is not None:
                on_retry(
                    {
                        "operation_name": operation_name,
                        "attempt": attempt,
                        "max_retries": effective_max_retries,
                        "delay_seconds": round(delay_seconds, 4),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            if log is not None:
                log(
                    f"{operation_name} failed with retryable error "
                    f"(attempt {attempt}/{max_retries}): {exc}. "
                    f"sleep {delay_seconds:.1f}s before retry"
                )
            sleep_func(delay_seconds)

    raise RuntimeError("Unreachable: retry attempts exhausted unexpectedly.")


def _call_timeout_seconds() -> float | None:
    raw_ms = os.getenv("GOOGLE_GENAI_TIMEOUT_MS", "").strip()
    if raw_ms:
        try:
            timeout_seconds = float(raw_ms) / 1000.0
        except ValueError as exc:
            raise RuntimeError(
                f"GOOGLE_GENAI_TIMEOUT_MS must be an integer; got {raw_ms!r}."
            ) from exc
    else:
        timeout_seconds = DEFAULT_CALL_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return None
    return timeout_seconds


def _call_with_timeout(
    func: Callable[[], Any],
    *,
    operation_name: str,
    timeout_seconds: float | None,
) -> Any:
    if timeout_seconds is None:
        return func()
    output: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            output.put(("result", func()))
        except BaseException as exc:  # noqa: BLE001
            output.put(("error", exc))

    worker = threading.Thread(
        target=run,
        name=f"{operation_name} timeout worker",
        daemon=True,
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError(
            f"{operation_name} timed out after {timeout_seconds:.1f}s"
        )
    kind, value = output.get_nowait()
    if kind == "error":
        raise value
    return value
