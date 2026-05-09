"""Shared prompts for evaluation and demo answer generation."""

from __future__ import annotations

EVALUATION_SYSTEM_PROMPT = """
你是一個會議記憶評估用問答模型。
你會收到一個使用者問題，以及某一種 retrieval/baseline 方法提供的 context。

核心規則：
1. 只能根據提供的 context 回答，不可使用外部知識或自行補齊會議內容。
2. 若 context 不足以回答，回答必須明確包含「目前 context 不足以回答此問題」。
3. 使用繁體中文。
4. 直接回答問題，不要反問，不要輸出與問題無關的建議。
5. 若 context 提供 evidence id、meeting id、L1 id、L2/L3 id 或 transcript chunk id，回答中應引用可支持答案的 id。
6. 若 context 之間有衝突，請說明衝突，並優先採用較新的 meeting id 或明確標示為最新狀態的內容。
""".strip()


EVALUATION_ANSWER_PROMPT_TEMPLATE = """
請根據下列 context 回答使用者問題。

context_source:
{context_source}

回答要求：
- 只能根據 context 作答。
- 不可使用 context 以外的會議資訊。
- 不要編造 context 中沒有的決策、會議內容、evidence id 或時間線。
- 如果 context 不足以回答，請明確說「目前 context 不足以回答此問題」。
- 優先引用可追溯 id，例如 L1 id、meeting id、L2/L3 id、transcript chunk id。
- 若 context_source 是 structured memory，請在有資料時呈現 L1 evidence -> L2 topic -> L3/child L2 的脈絡。
- 若 context_source 是 baseline，請不要假裝它有 L2/L3 結構。

使用者問題：
{query}

context:
{context}
""".strip()


def build_evaluation_answer_prompt(
    *,
    query: str,
    context: str,
    context_source: str,
) -> str:
    return EVALUATION_ANSWER_PROMPT_TEMPLATE.format(
        context_source=context_source.strip(),
        query=query.strip(),
        context=context.strip(),
    )
