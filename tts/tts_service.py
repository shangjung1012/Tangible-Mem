from collections.abc import Callable

from tts.google.google_tts import synthesize as google_synthesize
from tts.yating.yating_tts import synthesize as yating_synthesize

ENGINES: dict[str, Callable] = {
    "google": google_synthesize,
    "yating": yating_synthesize,
}


def synthesize(engine: str, text: str, output_path=None, **kwargs):
    engine_key = engine.lower()
    if engine_key not in ENGINES:
        raise ValueError(f"Unsupported TTS engine: {engine}")
    return ENGINES[engine_key](text, output_path, **kwargs)
