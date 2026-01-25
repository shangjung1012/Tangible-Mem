from google import genai
from google.genai import types

from dotenv import load_dotenv
from pathlib import Path
import os
from datetime import datetime

from config import ROOT, SYSTEM_PROMPT

load_dotenv(override=True)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    # max_output_tokens=256,
    # temperature=0.2,
)

chat = client.chats.create(
    model="gemini-2.5-flash",
    config=config,
)

first_prompt = (
    "我想做一個 Virtual Mentor 系統，模擬教授在 meeting 裡的提問方式，"
    "讓學生可以先練習怎麼回答跟準備研究進度。"
)

response = chat.send_message_stream(first_prompt)
print("Professor: ")
for chunk in response:
    print(chunk.text, end="")
    
while True:
    print("\n\nStudent: ")
    user_input = input()
    if user_input.lower() in ["exit", "quit", "q"]:
        break

    print("\nProfessor: ")
    response = chat.send_message_stream(user_input)
    for chunk in response:
        print(chunk.text, end="")

with open(ROOT / "record" / f"chat_history_{datetime.now().strftime('%m%d%H%M')}.txt", "w", encoding="utf-8") as f:
    for message in chat.get_history():
        f.write(f'{message.role}: {message.parts[0].text}\n')
