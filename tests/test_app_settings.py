"""Tests for the app_settings key-value store (settings drawer persistence)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import repositories
from backend.db.models import Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionLocal()
    yield session
    session.close()


class TestAppSettings:
    def test_missing_key_returns_none(self, db):
        assert repositories.get_app_setting(db, "tts_voice") is None

    def test_set_then_get(self, db):
        repositories.set_app_setting(db, "tts_voice", "af_heart")
        assert repositories.get_app_setting(db, "tts_voice") == "af_heart"

    def test_set_overwrites_existing(self, db):
        repositories.set_app_setting(db, "tts_voice", "af_heart")
        repositories.set_app_setting(db, "tts_voice", "bf_emma")
        assert repositories.get_app_setting(db, "tts_voice") == "bf_emma"
