import os
from pathlib import Path

from yating_tts_sdk import YatingClient

API_URL = "https://tts.api.yating.tw/v2/speeches/short"


def synthesize(
    text: str,
    output_path: str | Path | None = None,
    *,
    api_key: str | None = None,
    text_type: str = YatingClient.TYPE_TEXT,
    model: str = YatingClient.MODEL_ZHEN_FEMALE_1,
    speed: float = 1.0,
    pitch: float = 1.0,
    energy: float = 1.0,
    encoding: str = YatingClient.ENCODING_MP3,
    sample_rate: int = YatingClient.SAMPLE_RATE_16K,
):
    key = api_key or os.getenv("YATING_API_KEY")
    if not key:
        raise RuntimeError("YATING_API_KEY is required")

    output_stem = Path(output_path) if output_path else Path(__file__).parent / "yating_output"
    output_stem.parent.mkdir(parents=True, exist_ok=True)

    client = YatingClient(API_URL, key)
    client.synthesize(text, text_type, model, speed, pitch, energy, encoding, sample_rate, str(output_stem))

    suffix = f".{encoding.lower()}" if isinstance(encoding, str) else ".mp3"
    return output_stem.with_suffix(suffix) if not output_stem.suffix else output_stem
