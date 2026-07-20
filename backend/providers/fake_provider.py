"""Deterministic canned provider for tests and offline demos."""
from __future__ import annotations

import json
import logging
from typing import Optional

from backend.providers.base import LLMProvider

logger = logging.getLogger("preppilot.providers.fake")

_CANNED_QUESTIONS = [
    {
        "question": "Tell me about a time you had a disagreement with a teammate about a technical decision. What did you do?",
        "category": "behavioral",
        "targets_competency": "conflict_resolution",
    },
    {
        "question": "Design a URL shortener that handles 100 million redirects per day. Walk me through your high-level architecture.",
        "category": "system_design",
        "targets_competency": "system_design_fundamentals",
    },
    {
        "question": "What is the difference between optimistic and pessimistic locking, and when would you choose each?",
        "category": "technical_concept",
        "targets_competency": "concurrency",
    },
    {
        "question": "Describe a project you owned end-to-end. What was the measurable impact?",
        "category": "behavioral",
        "targets_competency": "ownership",
    },
    {
        "question": "How would you scale the URL shortener's data layer if reads grew 10x? Discuss caching and sharding trade-offs.",
        "category": "system_design",
        "targets_competency": "scalability",
    },
    {
        "question": "Explain how an index speeds up a database query and when adding one can hurt performance.",
        "category": "technical_concept",
        "targets_competency": "databases",
    },
]


class FakeProvider(LLMProvider):
    name = "fake"
    model = "canned-v1"

    def __init__(self) -> None:
        self._question_idx = 0

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.4,
        think: Optional[bool] = None,
    ) -> str:
        title = (json_schema or {}).get("title", "")
        if title == "InterviewerTurn":
            return json.dumps(self._interviewer_turn())
        if title == "FeedbackResult":
            return json.dumps(self._feedback())
        if title == "ReportResult":
            return json.dumps(self._report())
        if title == "QuestionBankResult":
            return json.dumps(self._question_bank())
        return "This is a canned response from the fake provider."

    def _interviewer_turn(self) -> dict:
        canned = _CANNED_QUESTIONS[self._question_idx % len(_CANNED_QUESTIONS)]
        self._question_idx += 1
        return {
            "question": canned["question"],
            "category": canned["category"],
            "is_followup": False,
            "targets_competency": canned["targets_competency"],
            "rationale": "Canned question for offline demo.",
        }

    @staticmethod
    def _feedback() -> dict:
        return {
            "scores": {
                "content_relevance": 7,
                "structure": 6,
                "specificity": 6,
                "technical_accuracy": 7,
                "delivery": 7,
                "overall": 7,
            },
            "star_completeness": {
                "situation": True,
                "task": True,
                "action": True,
                "result": False,
            },
            "strengths": [
                "You clearly described the situation and your specific role in it.",
                "You named concrete technologies rather than speaking in generalities.",
            ],
            "improvements": [
                {
                    "issue": "The answer ended without a measurable result.",
                    "fix": "Close with one sentence of impact, e.g. 'This cut deploy time from 40 to 12 minutes.'",
                },
                {
                    "issue": "Some claims stayed vague ('it improved a lot').",
                    "fix": "Attach a number or comparison to each key claim.",
                },
            ],
            "delivery_feedback": "Pace was steady and fillers were low; add a brief pause before key points for emphasis.",
            "coaching_summary": "Solid STAR setup — now land the Result with a concrete metric to make the story complete.",
        }

    @staticmethod
    def _report() -> dict:
        return {
            "overall_score": 6.8,
            "category_scores": {
                "behavioral": 7.0,
                "system_design": 6.5,
                "technical_concept": 7.0,
            },
            "strengths": [
                "Consistently strong situation/task framing in behavioral answers.",
                "Good use of concrete technologies and named tools.",
                "Clear requirement-gathering at the start of design answers.",
            ],
            "development_areas": [
                "Behavioral answers frequently omit a measurable Result.",
                "System design answers stop before failure modes and trade-offs.",
                "Technical explanations could go one level deeper on internals.",
            ],
            "delivery_summary": {
                "avg_wpm": 138.0,
                "avg_filler_rate": 0.021,
                "avg_confidence": 72.0,
                "biggest_habit_to_fix": "Trailing off at the end of answers instead of closing with impact.",
            },
            "trends": None,
            "practice_plan": [
                {
                    "focus": "STAR results",
                    "drill": "Rewrite 5 past answers so each ends with a one-sentence quantified result.",
                    "target_metric": "result present in 4/4 STAR elements",
                },
                {
                    "focus": "Design trade-offs",
                    "drill": "For 3 designs, list two failure modes and one mitigation each before ending.",
                    "target_metric": "structure score >= 8",
                },
                {
                    "focus": "Closing delivery",
                    "drill": "Record 3 answers and practice a firm final sentence, no trailing filler.",
                    "target_metric": "filler_rate < 3%",
                },
            ],
        }

    @staticmethod
    def _question_bank() -> dict:
        difficulties = ["easy", "medium", "hard"]
        return {
            "questions": [
                {
                    "category": q["category"],
                    "text": q["question"],
                    "targets_competency": q["targets_competency"],
                    "difficulty": difficulties[i % len(difficulties)],
                }
                for i, q in enumerate(_CANNED_QUESTIONS)
            ]
        }
