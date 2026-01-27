from datetime import datetime

from google import genai
from google.genai import types

from config import SYSTEM_PROMPT, GEMINI_API_KEY
from utli import record

MODEL_NAME = "gemini-2.5-flash"
INITIAL_STUDENT_PROMPT = (
    "我想做一個 Virtual Mentor 系統，模擬教授在 meeting 裡的提問方式，"
    "讓學生可以先練習怎麼回答跟準備研究進度。"
)


def build_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def build_chat(client: genai.Client) -> genai.chats.Chat:
    print(SYSTEM_PROMPT[:500])
    print('=' * 100)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.25,
        # max_output_tokens=256,
    )
    return client.chats.create(model=MODEL_NAME, config=config)


def stream_professor_reply(chat: genai.chats.Chat, prompt: str) -> str:
    print("\nProfessor:")
    response = chat.send_message_stream(prompt)
    full_text = ""
    for chunk in response:
        text = chunk.text or ""
        print(text, end="")
        full_text += text
    print()
    return full_text.strip()


def get_student_input() -> str:
    print("\nStudent:")
    return input().strip()


def run_chat(chat: genai.chats.Chat, record_file: str, initial_prompt: str) -> None:
    student_text = initial_prompt.strip()
    print("Student:")
    print(student_text)
    record("Student", student_text, record_file)

    while True:
        professor_text = stream_professor_reply(chat, student_text)
        record("Professor", professor_text, record_file)

        student_text = get_student_input()
        if student_text.lower() in {"exit", "quit", "q"}:
            break
        record("Student", student_text, record_file)


def main() -> None:
    client = build_client()
    chat = build_chat(client)
    record_file = f"chat_history_{datetime.now().strftime('%m%d%H%M')}.txt"
    run_chat(chat, record_file, INITIAL_STUDENT_PROMPT)


if __name__ == "__main__":
    main()
