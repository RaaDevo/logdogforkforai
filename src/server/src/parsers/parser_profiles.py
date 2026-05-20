from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from lib.database import SessionLocal
from lib.models import ParserProfile


@dataclass
class LearnedProfile:
    fingerprint: str
    domain: str
    profile_name: str | None
    detected_format: str
    structural_class: str
    parser_key: str
    extraction_strategy: str
    schema: dict[str, Any]
    confidence: float
    health_score: float
    usage_count: int
    success_count: int
    failure_count: int


class ParserProfileStore:
    def __init__(self, promote_threshold: int = 3):
        self.promote_threshold = promote_threshold
        self._metrics: dict[str, int] = {
            "profile_hits": 0,
            "profile_lookups": 0,
            "llm_bypasses": 0,
            "profile_promotions": 0,
            "profile_demotions": 0,
        }

    def lookup(
        self,
        fingerprint: str,
        domain: str,
        profile_name: str | None,
        min_confidence: float,
    ) -> LearnedProfile | None:
        self._metrics["profile_lookups"] += 1
        db = SessionLocal()
        try:
            query = db.query(ParserProfile).filter(
                ParserProfile.fingerprint == fingerprint,
                ParserProfile.domain == domain,
                ParserProfile.confidence >= min_confidence,
            )
            if profile_name is not None:
                query = query.filter(ParserProfile.profile_name == profile_name)

            row = query.order_by(ParserProfile.confidence.desc(), ParserProfile.health_score.desc()).first()
            if row is None:
                return None
            self._metrics["profile_hits"] += 1
            return self._to_learned(row)
        finally:
            db.close()

    def upsert_validated(self, profile: LearnedProfile) -> None:
        db = SessionLocal()
        try:
            row = self._find_row(db, profile.fingerprint, profile.domain, profile.profile_name, profile.detected_format)
            if row is None:
                row = ParserProfile(
                    fingerprint=profile.fingerprint,
                    domain=profile.domain,
                    profile_name=profile.profile_name,
                    detected_format=profile.detected_format,
                )
                db.add(row)

            row.structural_class = profile.structural_class
            row.parser_key = profile.parser_key
            row.extraction_strategy = profile.extraction_strategy
            row.schema = profile.schema
            row.confidence = max(0.0, min(profile.confidence, 1.0))
            row.health_score = max(0.0, min(profile.health_score, 1.0))
            row.usage_count = max(row.usage_count, profile.usage_count)
            row.success_count = max(row.success_count, profile.success_count)
            row.failure_count = max(row.failure_count, profile.failure_count)
            row.last_used = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def update_feedback(
        self,
        fingerprint: str,
        domain: str,
        profile_name: str | None,
        detected_format: str,
        success: bool,
    ) -> None:
        db = SessionLocal()
        try:
            row = self._find_row(db, fingerprint, domain, profile_name, detected_format)
            if row is None:
                return

            row.usage_count = (row.usage_count or 0) + 1
            if success:
                row.success_count = (row.success_count or 0) + 1
                if row.success_count >= self.promote_threshold:
                    prior = row.confidence
                    row.confidence = min(1.0, (row.confidence or 0.0) + 0.08)
                    if row.confidence > prior:
                        self._metrics["profile_promotions"] += 1
            else:
                row.failure_count = (row.failure_count or 0) + 1
                prior = row.confidence
                row.confidence = max(0.0, (row.confidence or 0.0) * 0.85)
                if row.confidence < prior:
                    self._metrics["profile_demotions"] += 1

            total = (row.success_count or 0) + (row.failure_count or 0)
            row.health_score = ((row.success_count or 0) / total) if total else 0.5
            row.last_used = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def mark_llm_bypass(self) -> None:
        self._metrics["llm_bypasses"] += 1

    def stats(self) -> dict[str, Any]:
        db = SessionLocal()
        try:
            persisted_total = db.query(ParserProfile).count()
        finally:
            db.close()
        return {**self._metrics, "persisted_total_profiles": persisted_total}

    @staticmethod
    def _find_row(db: Any, fingerprint: str, domain: str, profile_name: str | None, detected_format: str) -> ParserProfile | None:
        query = db.query(ParserProfile).filter(
            ParserProfile.fingerprint == fingerprint,
            ParserProfile.domain == domain,
            ParserProfile.detected_format == detected_format,
        )
        if profile_name is not None:
            query = query.filter(ParserProfile.profile_name == profile_name)
        return query.first()

    @staticmethod
    def _to_learned(row: ParserProfile) -> LearnedProfile:
        return LearnedProfile(
            fingerprint=row.fingerprint,
            domain=row.domain,
            profile_name=row.profile_name,
            detected_format=row.detected_format,
            structural_class=row.structural_class,
            parser_key=row.parser_key,
            extraction_strategy=row.extraction_strategy,
            schema=dict(row.schema or {}),
            confidence=float(row.confidence or 0.0),
            health_score=float(row.health_score or 0.5),
            usage_count=int(row.usage_count or 0),
            success_count=int(row.success_count or 0),
            failure_count=int(row.failure_count or 0),
        )
