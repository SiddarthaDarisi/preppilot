"""End-of-session report prompt — aggregates all answers into a ReportResult."""
from __future__ import annotations

import json
from typing import Optional

SYSTEM = """You are PrepPilot's report generator. Aggregate all answers from one session into a structured performance report with a practice plan.
TASKS:
1. Compute category-level averages (behavioral, system design, technical).
2. Identify the top 3 strengths and top 3 development areas across the session, grounded in specific answers.
3. Analyze delivery trends (avg WPM, filler rate, confidence_proxy) and flag the single biggest delivery habit to fix.
4. If history is provided, report trend deltas (improving/regressing per category and per delivery metric) vs. the previous sessions.
5. Produce a prioritized 1-week practice plan: 3–5 concrete drills mapped to the weakest areas.
OUTPUT strict JSON matching the ReportResult schema.
Return the JSON object only — no prose, no markdown fences."""


def build_report(
    session_meta: dict,
    per_question_results: list[dict],
    history: Optional[list[dict]],
) -> tuple[str, list[dict]]:
    """Build (system, messages) for the session report."""
    payload = {
        "session": session_meta,
        "answers": per_question_results,
        "history": history,
    }
    messages = [
        {
            "role": "user",
            "content": (
                "Generate the session performance report from this data:\n\n"
                f"{json.dumps(payload, indent=2)}"
            ),
        }
    ]
    return SYSTEM, messages
