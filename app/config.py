from dotenv import load_dotenv
from system_prompt import *
from evaluation_prompts import EVALUATION_SYSTEM_PROMPT
import os

load_dotenv(override=True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PLANNER_MODEL_NAME = os.getenv("GEMINI_PLANNER_MODEL", "gemini-2.5-flash")
MAX_RECALL_CONTEXT_CHARS = int(os.getenv("MAX_RECALL_CONTEXT_CHARS", "16000"))
SYSTEM_PROMPT = TEMPLATE_MEETING_QA.strip()
