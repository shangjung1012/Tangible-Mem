import os
from pathlib import Path
from typing import Iterable

from google.cloud import texttospeech

DEFAULT_LANGUAGE = "cmn-TW"
DEFAULT_VOICE = "cmn-TW-Wavenet-C"
DEFAULT_ENCODING = texttospeech.AudioEncoding.MP3


def synthesize(
    text: str,
    output_path: str | Path | None = None,
    *,
    language_code: str = DEFAULT_LANGUAGE,
    voice_name: str = DEFAULT_VOICE,
    speaking_rate: float = 1.0,
    pitch: float = 0.0,
    effects_profile_id: Iterable[str] | None = None,
    credentials_path: str | Path | None = None,
):
    base_dir = Path(__file__).parent
    credentials = Path(credentials_path) if credentials_path else base_dir / "tts_credential.json"
    if not credentials.exists():
        raise FileNotFoundError(f"Google credential not found at {credentials}")
    if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials)

    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=DEFAULT_ENCODING,
        speaking_rate=speaking_rate,
        pitch=pitch,
        effects_profile_id=list(effects_profile_id) if effects_profile_id else [],
    )
    response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

    output_file = Path(output_path) if output_path else base_dir / "output.mp3"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(response.audio_content)
    return output_file
