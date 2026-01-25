from google import genai
from google.genai import types

from dotenv import load_dotenv
from pathlib import Path
import os

from config import APP_ROOT, SYSTEM_PROMPT

load_dotenv(override=True)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    # max_output_tokens=256,
    # temperature=0.2,
)

transcript_path = APP_ROOT.parent / "transcript/250227.csv"

prompt = "我想做一個 Virtual Mentor 系統，模擬教授在 meeting 裡的提問方式，讓學生可以先練習怎麼回答跟準備研究進度。"

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        types.Part.from_bytes(
            data=transcript_path.read_bytes(),
            mime_type="text/plain",
        ),
        prompt
    ],
    config=config,
)
print(response.text)
