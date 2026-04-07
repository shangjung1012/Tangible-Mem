from datetime import datetime

from google import genai

from agent import MeetingQAAgent
from config import GEMINI_API_KEY, SYSTEM_PROMPT
from runtime_log import log_assistant_answer, log_user_question
from utli import record

INITIAL_STUDENT_PROMPT = (
    "針對「it's- I'm not worrying about it I mean, because we do have digits training data that we have from」"
    "，這件事目前是已決策、待驗證，還是尚未定案？"
)


def build_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def print_assistant_reply(text: str) -> None:
    print("\nAssistant:")
    print(text)


def get_student_input() -> str:
    print("\nUser:")
    return input().strip()


def run_chat(agent: MeetingQAAgent, record_file: str, initial_prompt: str) -> None:
    student_text = initial_prompt.strip()
    print(SYSTEM_PROMPT[:500])
    print('=' * 100)
    print("User:")
    print(student_text)
    log_user_question(student_text)
    record("User", student_text, record_file)

    while True:
        try:
            assistant_text = agent.ask(student_text)
        except Exception as exc:
            assistant_text = f"系統錯誤：{exc}"

        print_assistant_reply(assistant_text)
        log_assistant_answer(assistant_text)
        record("Assistant", assistant_text, record_file)

        student_text = get_student_input()
        if student_text.lower() in {"exit", "quit", "q"}:
            break
        log_user_question(student_text)
        record("User", student_text, record_file)


def main() -> None:
    client = build_client()
    agent = MeetingQAAgent(client=client)
    record_file = f"chat_history_{datetime.now().strftime('%m%d%H%M')}.txt"
    run_chat(agent, record_file, INITIAL_STUDENT_PROMPT)


if __name__ == "__main__":
    main()
