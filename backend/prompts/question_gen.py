"""Question-bank generation prompt — competency-mapped questions from a JD."""
from __future__ import annotations

import json

SYSTEM = """You are PrepPilot's question-bank generator. Given a role, seniority, and job description, produce a tailored interview question bank.
RULES:
1. Extract the key competencies from the job description and map every question to one.
2. Behavioral questions must be STAR-elicitable and competency-mapped (ownership, collaboration, conflict, ambiguity, impact, learning-from-failure).
3. System design questions must be scoped to the seniority and the JD's domain.
4. Technical-concept questions must test fundamentals of the JD's stack.
5. No duplicate or near-duplicate questions.
6. Vary difficulty across easy, medium, and hard.
7. If "exclude_questions" is provided, none of the generated questions may repeat or closely paraphrase any of them.
8. If "prioritize_competencies" is provided, weight your question choices toward those competencies (they are the candidate's historically weakest areas) without ignoring the requested category counts.
OUTPUT strict JSON matching: {"questions": [{"category": "behavioral | system_design | technical_concept | coding_concept", "text": "<question>", "targets_competency": "<competency>", "difficulty": "easy | medium | hard"}]}
Return the JSON object only — no prose, no markdown fences."""


def build_question_gen(
    role: str,
    seniority: str,
    jd_text: str,
    n_behavioral: int = 4,
    n_system_design: int = 2,
    n_technical: int = 3,
    exclude: list[str] | None = None,
    prioritize_competencies: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """Build (system, messages) to generate a question bank from a JD.

    `exclude`: question texts NOT to repeat (recent-session de-dup).
    `prioritize_competencies`: [{"competency": str, "avg_overall": float}] —
    the candidate's weakest areas, biasing new questions toward them (Adaptive mode).
    """
    payload = {
        "role": role,
        "seniority": seniority,
        "jd_text": jd_text or "(none provided)",
        "counts": {
            "behavioral": n_behavioral,
            "system_design": n_system_design,
            "technical_concept": n_technical,
        },
    }
    if exclude:
        payload["exclude_questions"] = exclude
    if prioritize_competencies:
        payload["prioritize_competencies"] = prioritize_competencies
    messages = [
        {
            "role": "user",
            "content": (
                "Generate the question bank with exactly the requested counts per "
                f"category:\n\n{json.dumps(payload, indent=2)}"
            ),
        }
    ]
    return SYSTEM, messages
