"""On-demand exemplary answer for a single question ("Show a strong answer").
Plain text output (not JSON) — short and cheap, no_think for speed.

Two modes: with the candidate's own transcript it rewrites THEIR answer into a
stronger version (keeping their real content, fixing the gaps); without it, it
writes a generic exemplary answer."""
from __future__ import annotations

SYSTEM_GENERIC = """You are an expert interview coach. Given an interview question, a role, and a
seniority level, write a concise exemplary answer a strong candidate would give.
RULES:
1. 150-220 words.
2. Match the answer shape to the QUESTION, not the category label:
   - A story/experience question ("tell me about a time...") → STAR (Situation, Task, Action, Result) with a concrete, quantified result.
   - A direct/screening question ("what are your salary expectations", "tell me about yourself", "why this company", strengths/weaknesses) → answer it directly and appropriately; do NOT force a STAR story. For salary: give a confident researched range with a one-line justification. For "tell me about yourself": present role → relevant highlights → why this role.
   - Technical/system-design → definition/approach first, then supporting detail.
3. Write in first person, as the candidate would speak it.
4. No preamble like "Here's an example" — output the answer only, no markdown, no headers."""

SYSTEM_REWRITE = """You are an expert interview coach. The candidate just answered a question and
wants to see how their OWN answer could be stronger. Rewrite THEIR answer into an
improved version.
RULES:
1. Build on what they actually said — keep their real details/story/numbers. Do NOT invent a different story.
2. Match the shape to the QUESTION, not the category label. Only use STAR (Situation, Task, Action, Result) for genuine story/experience questions ("tell me about a time..."). For direct questions (salary expectations, "tell me about yourself", "why this company", strengths/weaknesses) do NOT impose a STAR story — just make their direct answer sharper, more specific, and better-scoped.
3. Fix the real gaps: add a concrete quantified result where a story lacks one, tighten structure, cut filler and vagueness.
4. Where they gave no detail to build on, insert a clearly bracketed placeholder like "[e.g. reduced load time by 40%]" so they know to fill it with their real number.
5. 150-230 words, first person, spoken style.
6. Output the improved answer only — no preamble, no markdown headers, no commentary about what you changed."""


def build_model_answer(
    question: str,
    role: str,
    seniority: str,
    category: str,
    candidate_answer: str | None = None,
) -> tuple[str, list[dict]]:
    answer = (candidate_answer or "").strip()
    if answer:
        content = (
            f"Role: {role}\nSeniority: {seniority}\nQuestion category: {category}\n"
            f"Question: {question}\n\n"
            f"The candidate's actual answer:\n\"\"\"\n{answer}\n\"\"\"\n\n"
            "Rewrite it into a stronger version now."
        )
        return SYSTEM_REWRITE, [{"role": "user", "content": content}]

    content = (
        f"Role: {role}\nSeniority: {seniority}\nQuestion category: {category}\n"
        f"Question: {question}\n\nWrite the exemplary answer now."
    )
    return SYSTEM_GENERIC, [{"role": "user", "content": content}]
