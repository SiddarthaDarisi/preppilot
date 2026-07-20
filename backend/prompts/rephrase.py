"""Rephrase one interview question into a fresh wording that tests the SAME
thing — the "Ask differently" drill button. Plain text, no_think, a touch of
temperature for variety."""
from __future__ import annotations

SYSTEM = """You reword interview questions. Given a question, produce ONE alternative phrasing that
a real interviewer might use to probe the SAME underlying competency — different words and angle,
same intent and difficulty. Do NOT answer it, do NOT change the topic, do NOT make it easier or
harder. Keep it 1-2 sentences. Output ONLY the reworded question, no quotes, no preamble, no
markdown."""


def build_rephrase(question: str, role: str, seniority: str, category: str) -> tuple[str, list[dict]]:
    content = (
        f"Role: {role}\nSeniority: {seniority}\nCategory: {category}\n"
        f"Original question: {question}\n\nReword it now."
    )
    return SYSTEM, [{"role": "user", "content": content}]
