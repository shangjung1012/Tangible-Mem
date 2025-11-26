from .tts_service import synthesize
from .google import synthesize as google_tts
from .yating import synthesize as yating_tts

__all__ = ["synthesize", "google_tts", "yating_tts"]
