from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib import request


TURN_PATTERN = re.compile(r"^\[(?P<speaker>[^\]]+)\]:\s*(?P<text>.*)$")
ROLE_MAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "teacher_speakers": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["teacher_speakers", "confidence", "reason"],
}
CHINESE_NUMERALS = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map diarized speakers to teacher/student roles with a local Ollama model."
    )
    parser.add_argument(
        "--input-dir",
        default="meeting_recording/transcript",
        help="Directory containing WhisperX TXT transcripts.",
    )
    parser.add_argument(
        "--output-dir",
        default="meeting_recording/transcript_role",
        help="Directory for relabeled transcripts and mapping JSON files.",
    )
    parser.add_argument(
        "--ollama-host",
        default=os.getenv("OLLAMA_HOST", "http://ollama:11434"),
        help="Ollama base URL.",
    )
    parser.add_argument(
        "--ollama-model",
        default=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        help="Ollama model name used for role mapping.",
    )
    parser.add_argument(
        "--pull-model",
        action="store_true",
        help="Pull the Ollama model automatically if it is missing.",
    )
    parser.add_argument(
        "--ollama-ready-timeout",
        type=int,
        default=180,
        help="Seconds to wait for Ollama service readiness.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=600,
        help="Seconds for one Ollama request.",
    )
    return parser.parse_args()


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset)
    return json.loads(body)


def wait_for_ollama(host: str, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            http_json(f"{host.rstrip('/')}/api/tags", timeout=10)
            return True
        except Exception:
            time.sleep(2)
    return False


def ensure_model(host: str, model: str, should_pull: bool, timeout: int) -> None:
    tags = http_json(f"{host.rstrip('/')}/api/tags", timeout=timeout)
    names = {item.get("name") for item in tags.get("models", [])}
    if model in names:
        return
    if not should_pull:
        raise RuntimeError(
            f"Ollama model '{model}' not found. Start with --pull-model or change OLLAMA_MODEL."
        )
    print(f"Pulling Ollama model: {model}", file=sys.stderr)
    http_json(
        f"{host.rstrip('/')}/api/pull",
        payload={"name": model, "stream": False},
        timeout=timeout,
    )


def read_turns(transcript_path: Path) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(transcript_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = TURN_PATTERN.match(raw_line.strip())
        if not match:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        turns.append(
            {
                "speaker": match.group("speaker").strip(),
                "text": text,
                "line_no": line_no,
            }
        )
    return turns


def build_speaker_stats(turns: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    stats: dict[str, dict[str, Any]] = {}
    speaker_order: list[str] = []

    for idx, turn in enumerate(turns):
        speaker = turn["speaker"]
        if speaker not in stats:
            speaker_order.append(speaker)
            stats[speaker] = {
                "speaker": speaker,
                "first_turn_index": idx,
                "first_line_no": turn["line_no"],
                "turn_count": 0,
                "char_count": 0,
            }

        item = stats[speaker]
        text = turn["text"]
        item["turn_count"] += 1
        item["char_count"] += len(text)

    return stats, speaker_order


def build_dialogue_excerpt(turns: list[dict[str, Any]], max_chars: int = 8000) -> str:
    lines = [f"[{turn['speaker']}]: {turn['text']}" for turn in turns]
    full_text = "\n".join(lines)
    if len(full_text) <= max_chars:
        return full_text

    segment_size = 40
    windows = [
        ("開頭", 0),
        ("中段", max((len(turns) - segment_size) // 2, 0)),
        ("結尾", max(len(turns) - segment_size, 0)),
    ]
    seen: set[int] = set()
    segments: list[str] = []

    for label, start in windows:
        excerpt_lines: list[str] = []
        for idx in range(start, min(start + segment_size, len(turns))):
            if idx in seen:
                continue
            seen.add(idx)
            turn = turns[idx]
            excerpt_lines.append(f"[{turn['speaker']}]: {turn['text']}")
        if excerpt_lines:
            segments.append(f"--- {label}片段 ---\n" + "\n".join(excerpt_lines))

    excerpt = "\n\n".join(segments)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 4] + "\n..."


def build_prompt(
    turns: list[dict[str, Any]],
    speaker_order: list[str],
    stats: dict[str, dict[str, Any]],
) -> str:
    speakers = ", ".join(speaker_order)
    turn_summary = "\n".join(
        f"- {speaker}: turn_count={stats[speaker]['turn_count']}, char_count={stats[speaker]['char_count']}"
        for speaker in speaker_order
    )
    dialogue_excerpt = build_dialogue_excerpt(turns)

    return f"""
你是會議逐字稿角色辨識器。任務是從 speaker diarization 的結果中找出唯一一位老師。

判斷原則：
1. 只有一位老師，但 diarization 可能把同一位老師切成多個 speaker id，所以 teacher_speakers 允許有多個 id。
2. 其他所有 speaker 都是學生。
3. 請優先根據實際對話內容與互動關係判斷誰在帶領會議、追問、要求釐清、指派下一步、總結研究方向。
4. 不要依賴 speaker 編號大小，也不要只看誰講得最多。
5. 只能輸出角色判斷結果，不要做摘要，不要整理重點，不要解釋會議內容。
6. 只能輸出 JSON，不要加任何額外文字。

請輸出這個 JSON：
{{
  "teacher_speakers": ["SPEAKER_01"],
  "confidence": 0.0,
  "reason": "一句簡短理由"
}}

限制：
- teacher_speakers 只能填下面出現過的 speaker id。
- teacher_speakers 至少 1 個，至多 3 個。
- 如果不確定，也必須選出最可能的一組。

speaker_ids:
{speakers}

basic_counts:
{turn_summary}

dialogue_excerpt:
{dialogue_excerpt}
""".strip()


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def ollama_generate(
    host: str,
    model: str,
    prompt: str,
    timeout: int,
    format_spec: str | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    response = http_json(
        f"{host.rstrip('/')}/api/generate",
        payload={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": format_spec,
            "options": {
                "temperature": 0,
            },
        },
        timeout=timeout,
    )
    raw_text = str(response.get("response", "")).strip()
    return extract_json_object(raw_text), raw_text


def build_retry_prompt(
    original_prompt: str,
    speaker_order: list[str],
    previous_response: str,
) -> str:
    speakers = ", ".join(speaker_order)
    previous_preview = previous_response[:1200]
    return f"""
你上一個回覆格式錯誤，因為你沒有輸出角色判斷 JSON。

這次請只做一件事：
從這些 speaker 中選出老師的 speaker id：{speakers}

絕對不要摘要會議內容。
絕對不要輸出 key_points、summary、meeting summary 之類欄位。
只能輸出這個 JSON：
{{
  "teacher_speakers": ["SPEAKER_01"],
  "confidence": 0.0,
  "reason": "一句簡短理由"
}}

你上一個錯誤回覆是：
{previous_preview}

以下是原始任務，請重新回答：

{original_prompt}
""".strip()


def extract_teacher_candidates(raw_result: dict[str, Any], raw_text: str) -> list[str] | str | None:
    candidate = raw_result.get("teacher_speakers")
    if candidate is None:
        candidate = raw_result.get("teacher_speaker")
    if candidate is None:
        candidate = raw_result.get("speaker")
    if candidate is None:
        candidate = raw_result.get("teacher")
    if candidate is None and isinstance(raw_result.get("result"), dict):
        nested = raw_result["result"]
        candidate = (
            nested.get("teacher_speakers")
            or nested.get("teacher_speaker")
            or nested.get("speaker")
            or nested.get("teacher")
        )
    if candidate is not None:
        return candidate

    speakers_from_text = re.findall(r"SPEAKER_\d+", raw_text)
    if speakers_from_text:
        return speakers_from_text
    return None


def canonicalize_speaker_id(value: str, valid_speakers: set[str]) -> str | None:
    if value in valid_speakers:
        return value

    normalized = value.strip()
    upper = normalized.upper()
    if upper in valid_speakers:
        return upper

    match = re.fullmatch(r"SPEAKER[_\s-]*(\d+)", upper)
    if match:
        candidate = f"SPEAKER_{int(match.group(1)):02d}"
        if candidate in valid_speakers:
            return candidate
        candidate = f"SPEAKER_{int(match.group(1))}"
        if candidate in valid_speakers:
            return candidate

    match = re.fullmatch(r"SPEAKER(\d+)", upper)
    if match:
        candidate = f"SPEAKER_{int(match.group(1)):02d}"
        if candidate in valid_speakers:
            return candidate
        candidate = f"SPEAKER_{int(match.group(1))}"
        if candidate in valid_speakers:
            return candidate

    match = re.fullmatch(r"SPK[_\s-]*(\d+)", upper)
    if match:
        candidate = f"SPEAKER_{int(match.group(1)):02d}"
        if candidate in valid_speakers:
            return candidate

    match = re.fullmatch(r"(\d+)", upper)
    if match:
        candidate = f"SPEAKER_{int(match.group(1)):02d}"
        if candidate in valid_speakers:
            return candidate

    return None


def has_valid_teacher_field(raw_result: dict[str, Any], raw_text: str, valid_speakers: set[str]) -> bool:
    teacher_speakers = extract_teacher_candidates(raw_result, raw_text)
    if isinstance(teacher_speakers, str):
        teacher_speakers = [teacher_speakers]
    if not isinstance(teacher_speakers, list):
        return False
    return any(isinstance(speaker, str) and speaker in valid_speakers for speaker in teacher_speakers)


def ask_ollama(
    host: str,
    model: str,
    prompt: str,
    timeout: int,
    speaker_order: list[str],
) -> tuple[dict[str, Any], str]:
    valid_speakers = set(speaker_order)
    raw_result, raw_text = ollama_generate(
        host=host,
        model=model,
        prompt=prompt,
        timeout=timeout,
        format_spec=ROLE_MAP_SCHEMA,
    )
    if has_valid_teacher_field(raw_result, raw_text, valid_speakers):
        return raw_result, raw_text

    retry_prompt = build_retry_prompt(prompt, speaker_order, raw_text)
    retry_result, retry_text = ollama_generate(
        host=host,
        model=model,
        prompt=retry_prompt,
        timeout=timeout,
        format_spec=ROLE_MAP_SCHEMA,
    )
    return retry_result, retry_text


def normalize_teacher_speakers(
    raw_result: dict[str, Any],
    stats: dict[str, dict[str, Any]],
    raw_text: str,
) -> tuple[list[str], float | None, str]:
    valid_speakers = set(stats)
    teacher_speakers = extract_teacher_candidates(raw_result, raw_text)
    if isinstance(teacher_speakers, str):
        teacher_speakers = [teacher_speakers]
    if not isinstance(teacher_speakers, list):
        preview = raw_text[:400] if raw_text else json.dumps(raw_result, ensure_ascii=False)
        raise RuntimeError(
            "LLM output must contain a teacher speaker field. "
            f"Raw response preview: {preview}"
        )

    normalized: list[str] = []
    for speaker in teacher_speakers:
        if not isinstance(speaker, str):
            continue
        canonical = canonicalize_speaker_id(speaker, valid_speakers)
        if canonical is not None and canonical not in normalized:
            normalized.append(canonical)

    if not normalized:
        preview = raw_text[:400] if raw_text else json.dumps(raw_result, ensure_ascii=False)
        raise RuntimeError(
            "LLM output did not contain any valid speaker ids. "
            f"Raw response preview: {preview}"
        )

    confidence = raw_result.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = None

    reason = str(raw_result.get("reason", "")).strip() or "No reason returned by the local model."
    return normalized[:3], confidence, reason


def student_label(index: int) -> str:
    numeral = CHINESE_NUMERALS.get(index)
    if numeral is not None:
        return f"學生{numeral}"
    return f"學生{index}"


def relabel_turns(
    turns: list[dict[str, Any]],
    teacher_speakers: list[str],
    speaker_order: list[str],
) -> tuple[list[str], dict[str, str]]:
    teacher_set = set(teacher_speakers)
    role_by_speaker: dict[str, str] = {}
    student_index = 1

    for speaker in speaker_order:
        if speaker in teacher_set:
            role_by_speaker[speaker] = "老師"
        else:
            role_by_speaker[speaker] = student_label(student_index)
            student_index += 1

    relabeled_lines = [f"[{role_by_speaker[turn['speaker']]}]: {turn['text']}" for turn in turns]
    return relabeled_lines, role_by_speaker


def process_one_file(
    transcript_path: Path,
    input_dir: Path,
    output_dir: Path,
    ollama_host: str,
    ollama_model: str,
    request_timeout: int,
) -> None:
    turns = read_turns(transcript_path)
    if not turns:
        print(f"Skip empty or unparsable transcript: {transcript_path}")
        return

    stats, speaker_order = build_speaker_stats(turns)
    prompt = build_prompt(turns, speaker_order, stats)
    raw_result, raw_text = ask_ollama(
        host=ollama_host,
        model=ollama_model,
        prompt=prompt,
        timeout=request_timeout,
        speaker_order=speaker_order,
    )

    teacher_speakers, confidence, reason = normalize_teacher_speakers(raw_result, stats, raw_text)
    relabeled_lines, role_by_speaker = relabel_turns(turns, teacher_speakers, speaker_order)

    relative = transcript_path.relative_to(input_dir)
    output_text_path = output_dir / relative
    output_json_path = output_text_path.with_suffix(".mapping.json")
    output_text_path.parent.mkdir(parents=True, exist_ok=True)

    output_text_path.write_text("\n".join(relabeled_lines) + "\n", encoding="utf-8")
    output_json_path.write_text(
        json.dumps(
            {
                "source_file": str(transcript_path.resolve()),
                "output_file": str(output_text_path.resolve()),
                "teacher_speakers": teacher_speakers,
                "role_by_speaker": role_by_speaker,
                "confidence": confidence,
                "reason": reason,
                "used_llm": True,
                "llm_raw_response": raw_text,
                "speaker_stats": stats,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Mapped {transcript_path.name}: teacher={teacher_speakers} -> {output_text_path}"
    )


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not input_dir.exists():
        raise RuntimeError(f"Transcript directory not found: {input_dir}")

    transcripts = sorted(path for path in input_dir.rglob("*.txt") if path.is_file())
    if not transcripts:
        print(f"No transcript files found under {input_dir}")
        return

    if not wait_for_ollama(args.ollama_host, args.ollama_ready_timeout):
        raise RuntimeError(f"Ollama is not ready at {args.ollama_host}.")

    ensure_model(
        host=args.ollama_host,
        model=args.ollama_model,
        should_pull=args.pull_model,
        timeout=args.request_timeout,
    )

    for transcript_path in transcripts:
        process_one_file(
            transcript_path=transcript_path,
            input_dir=input_dir,
            output_dir=output_dir,
            ollama_host=args.ollama_host,
            ollama_model=args.ollama_model,
            request_timeout=args.request_timeout,
        )


if __name__ == "__main__":
    main()
