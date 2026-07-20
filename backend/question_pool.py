"""Question pre-generation pool.

Turning a "next question" into an instant, zero-LLM-call pop() instead of a
30-60s Ollama round trip on every turn. Built once at session start (and
topped up lazily if it runs dry), backed by the QuestionBankItem table so
that questions are (a) reused across sessions for the same role instead of
re-generated every time, and (b) never repeat the candidate's recent history
(Adaptive mode) or, for Drill mode, are exactly the caller's chosen set.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from collections import deque
from typing import Optional

from sqlalchemy.orm import Session as OrmSession

from backend.config import Settings
from backend.db import models, repositories
from backend.prompts.question_gen import build_question_gen
from backend.providers.base import LLMProvider
from backend.schemas import InterviewerTurn, QuestionBankResult

logger = logging.getLogger("preppilot.question_pool")

# How far ahead to keep stocked. A small buffer keeps the one-time generation
# call cheap while still covering a full session without re-hitting the LLM.
POOL_BUFFER = 2


def _item_to_turn(item: models.QuestionBankItem, is_followup: bool = False) -> InterviewerTurn:
    return InterviewerTurn(
        question=item.text,
        category=item.category,  # type: ignore[arg-type]
        is_followup=is_followup,
        targets_competency=item.targets_competency,
        rationale="from question pool",
    )


class QuestionPool:
    def __init__(
        self,
        provider: LLMProvider,
        db: OrmSession,
        settings: Settings,
        session_row: models.Session,
        seed_bank_ids: Optional[list[int]] = None,
        mode: str = "adaptive",
    ) -> None:
        self.provider = provider
        self.db = db
        self.settings = settings
        self.session_row = session_row
        self.seed_bank_ids = seed_bank_ids or []
        self.mode = mode
        self._queue: deque[models.QuestionBankItem] = deque()

    @property
    def _focus_areas(self) -> list[str]:
        try:
            return json.loads(self.session_row.focus_areas)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def _allowed_categories(self) -> set[str]:
        """Question categories the session's focus areas permit. Empty set
        means "no restriction" (fall back to serving anything)."""
        focus = self._focus_areas
        if not focus:
            return set()
        allowed = set(focus)
        # "technical_concept" focus also covers coding-concept questions.
        if "technical_concept" in allowed:
            allowed.add("coding_concept")
        return allowed

    def remaining(self) -> int:
        return len(self._queue)

    def peek_texts(self) -> list[str]:
        """Non-destructive snapshot of queued question texts — used to
        prewarm the TTS cache for the whole session without consuming them."""
        return [item.text for item in self._queue]

    def build(self) -> None:
        """Synchronous — call via asyncio.to_thread. Safe to call more than
        once (e.g. to top up); re-running just refills the queue."""
        if self.mode == "drill" and self.seed_bank_ids:
            rows = repositories.get_bank_items_by_ids(self.db, self.seed_bank_ids)
            self._queue = deque(rows)
            if not rows:
                logger.warning(
                    "Drill session %s: none of seed_bank_ids %s resolved to bank rows",
                    self.session_row.id, self.seed_bank_ids,
                )
            return

        role = self.session_row.role
        seniority = self.session_row.seniority
        jd_hash = hashlib.sha256((self.session_row.jd_text or "").encode("utf-8")).hexdigest()

        candidates = repositories.get_bank_items(self.db, role, seniority, jd_hash)
        exclude_texts: set[str] = set()
        if self.mode == "adaptive":
            exclude_texts = repositories.get_recent_question_texts(self.db, role)
        candidates = [c for c in candidates if c.text.strip().lower() not in exclude_texts]
        # Only serve categories the user actually asked for. Without this, a
        # bank cached from a previous session (any category) leaks in — the
        # "I picked Behavioral but got system-design questions" bug.
        allowed = self._allowed_categories
        if allowed:
            candidates = [c for c in candidates if c.category in allowed]

        target = self.settings.session.max_questions + POOL_BUFFER
        if len(candidates) < target:
            candidates = candidates + self._generate_more(
                role, seniority, jd_hash, exclude_texts, needed=target - len(candidates)
            )

        random.shuffle(candidates)
        # Interleave by category so a shuffled-but-clustered bank doesn't
        # front-load one category (e.g. all behavioral first).
        by_category: dict[str, list[models.QuestionBankItem]] = {}
        for c in candidates:
            by_category.setdefault(c.category, []).append(c)
        interleaved: list[models.QuestionBankItem] = []
        while any(by_category.values()):
            for cat in list(by_category.keys()):
                bucket = by_category[cat]
                if bucket:
                    interleaved.append(bucket.pop(0))
        self._queue = deque(interleaved)

    def _generate_more(
        self,
        role: str,
        seniority: str,
        jd_hash: str,
        exclude_texts: set[str],
        needed: int,
    ) -> list[models.QuestionBankItem]:
        focus = self._focus_areas or ["behavioral", "system_design", "technical_concept"]
        # Split the deficit across the requested focus areas (min 1 each).
        per_area = max(1, needed // max(1, len(focus)))
        counts = {
            "n_behavioral": per_area if "behavioral" in focus else 0,
            "n_system_design": per_area if "system_design" in focus else 0,
            "n_technical": per_area if "technical_concept" in focus else 0,
        }
        prioritize = (
            repositories.get_weak_competencies(self.db, role) if self.mode == "adaptive" else None
        )
        system, messages = build_question_gen(
            role,
            seniority,
            self.session_row.jd_text,
            exclude=sorted(exclude_texts)[:50] or None,  # cap prompt size
            prioritize_competencies=prioritize or None,
            **counts,
        )
        try:
            result = self.provider.complete_json(
                system,
                messages,
                schema_model=QuestionBankResult,
                temperature=self.settings.llm.temperature,
                think=False,
            )
        except Exception as exc:  # ProviderError or validation failure — pool just stays smaller
            logger.warning("Question pool top-up generation failed: %s", exc)
            return []
        assert isinstance(result, QuestionBankResult)
        fresh = [q for q in result.questions if q.text.strip().lower() not in exclude_texts]
        return repositories.save_bank_items(self.db, role, seniority, jd_hash, fresh)

    def pop(self, category_hint: Optional[str] = None) -> Optional[InterviewerTurn]:
        if not self._queue:
            return None
        if category_hint:
            for i, item in enumerate(self._queue):
                if item.category == category_hint:
                    del self._queue[i]
                    return _item_to_turn(item)
        return _item_to_turn(self._queue.popleft())
