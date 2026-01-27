from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(override=True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ROOT = Path(__file__).parent.parent.resolve()
profile_path = ROOT / "app" / "profile.md"
profile_text = profile_path.read_text(encoding="utf-8")

transcript_path = ROOT / "transcript/250227.csv"
transcript_text = transcript_path.read_text(encoding="utf-8")

SYSTEM_PROMPT=f"""
你是一名教授，接下來你將與學生進行一場全新的研究會議，討論的主題與內容和這份逐字稿無關。
以下是你做為教授的個人設定與風格描述，請務必遵從這些設定來進行對話互動，並回傳對話內容：
{profile_text}

以下是之前教授與學生的會議逐字稿，但你必須表現得像逐字稿中的教授一樣，採用相同的提問風格與方式與學生互動，但內容與這次會議完全無關：
{transcript_text}
"""


