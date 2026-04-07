from dotenv import load_dotenv
from system_prompt import *
import os

load_dotenv(override=True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_RECALL_CONTEXT_CHARS = int(os.getenv("MAX_RECALL_CONTEXT_CHARS", "4000"))
SYSTEM_PROMPT = TEMPLATE_MEETING_QA.strip()
