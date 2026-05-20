from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from lib.database import SessionLocal
from lib.models import SchemaCacheEntry

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30 * 24 * 3600
MAX_CACHE_SIZE = 1000


@dataclass
class CachedSchema:
    schema_key: str
    format_name: str
    detected_format: str
    structural_class: str
    parser_key: str
    format_confidence: float
    domain: str
    profile_name: str | None
    columns: list[dict[str, Any]]
    extraction_strategy: str
    sample_hash: str
    fingerprint: str
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    null_rates: dict[str, float] = field(default_factory=dict)
    route_stats: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > DEFAULT_TTL_SECONDS

    @property
    def health_score(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total


class SchemaCache:
    def __init__(self, max_size: int = MAX_CACHE_SIZE, use_persistence: bool = True):
        self._cache: dict[str, CachedSchema] = {}
        self._max_size = max_size
        self._use_persistence = use_persistence

    def get(
        self,
        sample_lines: list[str],
        format_name: str,
        domain: str,
        profile_name: str | None = None,
    ) -> CachedSchema | None:
        sample_hash = self._compute_sample_hash(sample_lines)
        schema_key = self._schema_key(format_name, domain, sample_hash, profile_name)

        cached = self._cache.get(schema_key)
        if cached is None and self._use_persistence:
            cached = self._load_from_db(schema_key)
            if cached is not None:
                self._cache[schema_key] = cached

        if cached is None:
            return None

        if cached.is_expired:
            self._cache.pop(schema_key, None)
            return None

        cached.last_accessed = time.time()
        cached.access_count += 1
        if self._use_persistence:
            self._touch_db(schema_key)
        return cached

    def put(
        self,
        sample_lines: list[str],
        format_name: str,
        domain: str,
        columns: list[dict[str, Any]],
        extraction_strategy: str,
        profile_name: str | None = None,
        detected_format: str | None = None,
        structural_class: str | None = None,
        parser_key: str = "unified",
        format_confidence: float = 0.0,
        fingerprint: str | None = None,
    ) -> CachedSchema:
        sample_hash = self._compute_sample_hash(sample_lines)
        schema_key = self._schema_key(format_name, domain, sample_hash, profile_name)

        if len(self._cache) >= self._max_size:
            self._evict()

        resolved_fingerprint = fingerprint or sample_hash
        resolved_detected_format = detected_format or format_name
        resolved_structural_class = structural_class or "unstructured"

        cached = CachedSchema(
            schema_key=schema_key,
            format_name=format_name,
            detected_format=resolved_detected_format,
            structural_class=resolved_structural_class,
            parser_key=parser_key,
            format_confidence=max(0.0, min(format_confidence, 1.0)),
            domain=domain,
            profile_name=profile_name,
            columns=columns,
            extraction_strategy=extraction_strategy,
            sample_hash=sample_hash,
            fingerprint=resolved_fingerprint,
        )
        self._cache[schema_key] = cached
        if self._use_persistence:
            self._upsert_db(cached)
        return cached

    def get_by_fingerprint(
        self,
        fingerprint: str,
        domain: str = "unknown",
        profile_name: str | None = None,
        min_confidence: float = 0.8,
    ) -> CachedSchema | None:
        candidates = [
            cached
            for cached in self._cache.values()
            if cached.fingerprint == fingerprint
            and cached.domain == domain
            and (profile_name is None or cached.profile_name == profile_name)
            and cached.format_confidence >= min_confidence
            and not cached.is_expired
        ]
        if candidates:
            candidates.sort(
                key=lambda item: (item.format_confidence, item.health_score, item.access_count), reverse=True
            )
            candidate = candidates[0]
            candidate.last_accessed = time.time()
            return candidate

        if not self._use_persistence:
            return None

        db = SessionLocal()
        try:
            query = db.query(SchemaCacheEntry).filter(
                SchemaCacheEntry.fingerprint == fingerprint,
                SchemaCacheEntry.domain == domain,
                SchemaCacheEntry.format_confidence >= min_confidence,
            )
            if profile_name is not None:
                query = query.filter(SchemaCacheEntry.profile_name == profile_name)

            entry = query.order_by(
                SchemaCacheEntry.format_confidence.desc(),
                SchemaCacheEntry.success_count.desc(),
                SchemaCacheEntry.access_count.desc(),
            ).first()
            if entry is None:
                return None

            cached = self._to_cached(entry)
            if cached.is_expired:
                return None

            self._cache[cached.schema_key] = cached
            self._touch_db(cached.schema_key)
            return cached
        finally:
            db.close()

    def record_success(self, schema_key: str) -> None:
        cached = self._cache.get(schema_key)
        if cached:
            cached.success_count += 1
        if self._use_persistence:
            self._record_db_result(schema_key, success=True)

    def record_failure(self, schema_key: str, null_rates: dict[str, float]) -> None:
        cached = self._cache.get(schema_key)
        if cached:
            cached.failure_count += 1
            cached.null_rates.update(null_rates)
        if self._use_persistence:
            self._record_db_result(schema_key, success=False)

    def record_route_outcome(
        self,
        schema_key: str,
        *,
        detected_format: str,
        parser_key: str,
        profile_name: str | None,
        success: bool,
    ) -> None:
        route_key = f"{detected_format}|{parser_key}|{profile_name or 'default'}"
        cached = self._cache.get(schema_key)
        if cached is not None:
            bucket = cached.route_stats.get(route_key, {"success": 0, "failure": 0})
            bucket["success" if success else "failure"] = int(bucket.get("success" if success else "failure", 0)) + 1
            cached.route_stats[route_key] = bucket
        if self._use_persistence:
            self._record_db_route_outcome(schema_key=schema_key, route_key=route_key, success=success)

    def get_by_format(
        self,
        format_name: str,
        domain: str | None = None,
        max_count: int = 5,
    ) -> list[CachedSchema]:
        candidates: list[CachedSchema] = []
        for cached in self._cache.values():
            if cached.format_name != format_name:
                continue
            if domain and cached.domain != domain:
                continue
            if not cached.is_expired:
                candidates.append(cached)

        candidates.sort(key=lambda c: (-c.health_score, -c.access_count))
        return candidates[:max_count]

    def stats(self) -> dict[str, Any]:
        total = len(self._cache)
        expired = sum(1 for c in self._cache.values() if c.is_expired)
        healthy = sum(1 for c in self._cache.values() if c.health_score > 0.7)
        persisted_total = 0
        if self._use_persistence:
            db = SessionLocal()
            try:
                persisted_total = db.query(SchemaCacheEntry).count()
            finally:
                db.close()
        return {
            "total_schemas": total,
            "persisted_total_schemas": persisted_total,
            "expired": expired,
            "healthy": healthy,
            "max_size": self._max_size,
        }

    def clear(self) -> None:
        self._cache.clear()
        if self._use_persistence:
            db = SessionLocal()
            try:
                db.query(SchemaCacheEntry).delete()
                db.commit()
            finally:
                db.close()

    def _evict(self) -> None:
        expired_keys = [key for key, cached in self._cache.items() if cached.is_expired]
        for key in expired_keys:
            self._cache.pop(key, None)

        if len(self._cache) >= self._max_size:
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: (
                    self._cache[k].health_score,
                    self._cache[k].access_count,
                    self._cache[k].last_accessed,
                ),
            )
            for key in sorted_keys[: len(self._cache) - self._max_size + 10]:
                self._cache.pop(key, None)

    @staticmethod
    def _compute_sample_hash(sample_lines: list[str]) -> str:
        content = "\n".join(line[:200] for line in sample_lines[:20])
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:16]

    @staticmethod
    def _schema_key(format_name: str, domain: str, sample_hash: str, profile_name: str | None = None) -> str:
        profile_part = profile_name or "default"
        return f"{format_name}:{domain}:{profile_part}:{sample_hash}"

    def _load_from_db(self, schema_key: str) -> CachedSchema | None:
        db = SessionLocal()
        try:
            entry = db.query(SchemaCacheEntry).filter(SchemaCacheEntry.cache_key == schema_key).first()
            if entry is None:
                return None
            return self._to_cached(entry)
        finally:
            db.close()

    def _upsert_db(self, cached: CachedSchema) -> None:
        db = SessionLocal()
        try:
            existing = db.query(SchemaCacheEntry).filter(SchemaCacheEntry.cache_key == cached.schema_key).first()
            if existing is None:
                existing = SchemaCacheEntry(cache_key=cached.schema_key)
                db.add(existing)

            existing.format_name = cached.format_name
            existing.detected_format = cached.detected_format
            existing.structural_class = cached.structural_class
            existing.domain = cached.domain
            existing.profile_name = cached.profile_name
            existing.parser_key = cached.parser_key
            existing.format_confidence = cached.format_confidence
            existing.sample_hash = cached.sample_hash
            existing.fingerprint = cached.fingerprint
            existing.columns = json.dumps(cached.columns, ensure_ascii=True)
            existing.extraction_strategy = cached.extraction_strategy
            existing.success_count = cached.success_count
            existing.failure_count = cached.failure_count
            existing.access_count = cached.access_count
            existing.last_accessed = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def _touch_db(self, schema_key: str) -> None:
        db = SessionLocal()
        try:
            entry = db.query(SchemaCacheEntry).filter(SchemaCacheEntry.cache_key == schema_key).first()
            if entry is None:
                return
            entry.access_count = (entry.access_count or 0) + 1
            entry.last_accessed = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def _record_db_result(self, schema_key: str, success: bool) -> None:
        db = SessionLocal()
        try:
            entry = db.query(SchemaCacheEntry).filter(SchemaCacheEntry.cache_key == schema_key).first()
            if entry is None:
                return
            if success:
                entry.success_count = (entry.success_count or 0) + 1
            else:
                entry.failure_count = (entry.failure_count or 0) + 1
            entry.updated_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

    def _record_db_route_outcome(self, schema_key: str, route_key: str, success: bool) -> None:
        db = SessionLocal()
        try:
            entry = db.query(SchemaCacheEntry).filter(SchemaCacheEntry.cache_key == schema_key).first()
            if entry is None:
                return
            try:
                columns = json.loads(entry.columns)
            except json.JSONDecodeError:
                columns = []
            route_stats = {}
            if isinstance(columns, list) and columns and isinstance(columns[-1], dict):
                route_stats = columns[-1].get("_route_stats", {})
            bucket = route_stats.get(route_key, {"success": 0, "failure": 0})
            bucket["success" if success else "failure"] = int(bucket.get("success" if success else "failure", 0)) + 1
            route_stats[route_key] = bucket
            if isinstance(columns, list):
                if columns and isinstance(columns[-1], dict) and "_route_stats" in columns[-1]:
                    columns[-1]["_route_stats"] = route_stats
                else:
                    columns.append({"_route_stats": route_stats})
            entry.columns = json.dumps(columns, ensure_ascii=True)
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _to_cached(entry: SchemaCacheEntry) -> CachedSchema:
        now = time.time()
        created_at = entry.created_at.timestamp() if entry.created_at else now
        last_accessed = entry.last_accessed.timestamp() if entry.last_accessed else created_at
        try:
            columns = json.loads(entry.columns)
        except json.JSONDecodeError:
            columns = []

        route_stats: dict[str, dict[str, int]] = {}
        if isinstance(columns, list) and columns and isinstance(columns[-1], dict) and "_route_stats" in columns[-1]:
            route_stats = columns[-1].get("_route_stats", {})
            columns = columns[:-1]

        return CachedSchema(
            schema_key=entry.cache_key,
            format_name=entry.format_name,
            detected_format=entry.detected_format,
            structural_class=entry.structural_class,
            parser_key=entry.parser_key,
            format_confidence=float(entry.format_confidence or 0.0),
            domain=entry.domain,
            profile_name=entry.profile_name,
            columns=columns if isinstance(columns, list) else [],
            extraction_strategy=entry.extraction_strategy,
            sample_hash=entry.sample_hash,
            fingerprint=entry.fingerprint,
            created_at=created_at,
            last_accessed=last_accessed,
            access_count=int(entry.access_count or 0),
            success_count=int(entry.success_count or 0),
            failure_count=int(entry.failure_count or 0),
            route_stats=route_stats,
        )
