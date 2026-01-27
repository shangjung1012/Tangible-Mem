from pathlib import Path
from dotenv import load_dotenv
from system_prompt import *
import os

load_dotenv(override=True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ROOT = Path(__file__).parent.parent.resolve()
profile_path = ROOT / "app" / "profile.md"
profile_text = profile_path.read_text(encoding="utf-8")

transcript_path = ROOT / "transcript/250227.csv"
transcript_text = transcript_path.read_text(encoding="utf-8")

SYSTEM_PROMPT=TEMPLATE_3.format(
    profile_text=profile_text, transcript_text=transcript_text
)


