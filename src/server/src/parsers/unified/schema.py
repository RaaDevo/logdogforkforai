from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from parsers.contracts import ColumnDefinition
from parsers.few_shot_store import FewShotStore
from parsers.llm_engine import LlmEngine
from parsers.normalization import sanitize_identifier, unique_identifier
from parsers.schema_cache import SchemaCache

logger = logging.getLogger(__name__)

NULL_RATE_THRESHOLD = 0.6
MAX_REFINEMENT_ITERATIONS = 3


@dataclass
class SchemaInferenceResult:
    columns: list[ColumnDefinition]
    extraction_strategy: str
    confidence: float
    null_rates: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    from_cache: bool = False
    refined: bool = False


class SelfCorrectingSchemaInferer:
    def __init__(
        self,
        llm_engine: LlmEngine | None = None,
        schema_cache: SchemaCache | None = None,
        few_shot_store: FewShotStore | None = None,
    ):
        self.llm_engine = llm_engine or LlmEngine()
        self.schema_cache = schema_cache or SchemaCache()
        self.few_shot_store = few_shot_store or FewShotStore()

    def infer(
        self,
        sample_lines: list[str],
        format_name: str,
        domain: str = "unknown",
        profile_name: str | None = None,
        profile_context: dict[str, Any] | None = None,
    ) -> SchemaInferenceResult:
        warnings: list[str] = []

        cached = self.schema_cache.get(
            sample_lines=sample_lines[:20],
            format_name=format_name,
            domain=domain,
            profile_name=profile_name,
        )
        if cached:
            columns = [
                ColumnDefinition(
                    name=column["name"],
                    sql_type=column.get("sql_type", "TEXT"),
                    description=column.get("description", ""),
                    nullable=True,
                )
                for column in cached.columns
            ]
            return SchemaInferenceResult(
                columns=columns,
                extraction_strategy=cached.extraction_strategy,
                confidence=0.9,
                from_cache=True,
            )

        few_shot_schemas = self.few_shot_store.get_example_schemas(
            format_name=format_name,
            domain=domain,
            profile_name=profile_name,
            max_count=3,
        )
        invocation = self.llm_engine.infer_schema(
            sample_lines=sample_lines,
            detected_format=format_name,
            few_shot_schemas=few_shot_schemas,
            profile_context=profile_context,
        )

        if not invocation.success or invocation.response is None:
            fallback_columns = self._fallback_schema(sample_lines)
            warnings.append(f"LLM schema inference failed, using fallback schema: {invocation.warning}")
            return SchemaInferenceResult(
                columns=fallback_columns,
                extraction_strategy="per_line",
                confidence=0.5,
                warnings=warnings,
            )

        response = invocation.response
        columns = self._to_columns(response.columns)
        extraction_strategy = response.extraction_strategy.value
        confidence = response.confidence

        null_rates = self._estimate_null_rates(sample_lines, columns)
        refined = False

        for _ in range(MAX_REFINEMENT_ITERATIONS):
            high_null = {key: rate for key, rate in null_rates.items() if rate >= NULL_RATE_THRESHOLD}
            if not high_null:
                break

            refine_result = self.llm_engine.refine_schema(
                sample_lines=sample_lines,
                current_columns=[
                    {
                        "name": column.name,
                        "sql_type": column.sql_type,
                        "description": column.description,
                    }
                    for column in columns
                ],
                null_rates=high_null,
            )

            if not refine_result.success or refine_result.response is None:
                warnings.append(f"Schema refinement failed: {refine_result.warning}")
                break

            response = refine_result.response
            columns = self._to_columns(response.columns)
            extraction_strategy = response.extraction_strategy.value
            confidence = min(1.0, (confidence + response.confidence) / 2)
            null_rates = self._estimate_null_rates(sample_lines, columns)
            refined = True

        self.schema_cache.put(
            sample_lines=sample_lines[:20],
            format_name=format_name,
            domain=domain,
            columns=[
                {
                    "name": column.name,
                    "sql_type": column.sql_type,
                    "description": column.description,
                    "nullable": True,
                }
                for column in columns
            ],
            extraction_strategy=extraction_strategy,
            profile_name=profile_name,
            detected_format=format_name,
            structural_class=response.format_category.value,
            parser_key="unified",
            format_confidence=confidence,
        )

        self.few_shot_store.record_successful_parse(
            format_name=format_name,
            domain=domain,
            sample_lines=sample_lines[:5],
            schema={
                "columns": [column.name for column in columns],
                "strategy": extraction_strategy,
            },
            confidence=confidence,
            profile_name=profile_name,
        )

        cost_summary = self.llm_engine.get_cost_summary()
        logger.info(
            "Schema inference complete for %s/%s: model=%s cost=$%.6f tokens=%d refined=%s",
            format_name,
            domain,
            cost_summary["model"],
            cost_summary["total_cost_usd"],
            cost_summary["total_tokens"],
            refined,
        )

        return SchemaInferenceResult(
            columns=columns,
            extraction_strategy=extraction_strategy,
            confidence=confidence,
            null_rates=null_rates,
            warnings=warnings,
            refined=refined,
        )

    @staticmethod
    def _to_columns(columns: list[Any]) -> list[ColumnDefinition]:
        result: list[ColumnDefinition] = []
        seen: set[str] = set()

        for column in columns:
            safe_name = unique_identifier(SelfCorrectingSchemaInferer._sanitize(column.name), seen)
            seen.add(safe_name)
            result.append(
                ColumnDefinition(
                    name=safe_name,
                    sql_type=column.sql_type,
                    description=column.description or f"Inferred field '{safe_name}'.",
                    nullable=True,
                )
            )

        return result

    @staticmethod
    def _estimate_null_rates(sample_lines: list[str], columns: list[ColumnDefinition]) -> dict[str, float]:
        if not sample_lines or not columns:
            return {}

        null_counts = {column.name: 0 for column in columns}
        total = min(len(sample_lines), 100)

        for line in sample_lines[:total]:
            line_lower = line.lower()
            for column in columns:
                if column.name not in line_lower and not SelfCorrectingSchemaInferer._has_value_hint(line, column.name):
                    null_counts[column.name] += 1

        return {name: round(count / total, 3) for name, count in null_counts.items()}

    @staticmethod
    def _has_value_hint(line: str, column_name: str) -> bool:
        patterns = [
            rf"\b{column_name}\s*[:=]",
            rf"\b{column_name.replace('_', ' ')}\s*[:=]",
        ]
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _fallback_schema(lines: list[str]) -> list[ColumnDefinition]:
        columns = [
            ColumnDefinition(name="message", sql_type="TEXT", description="Primary log message."),
            ColumnDefinition(name="log_level", sql_type="TEXT", description="Detected log level."),
            ColumnDefinition(name="source", sql_type="TEXT", description="Source or subsystem identifier."),
        ]

        sample_text = "\n".join(lines[:20]).lower()
        if "timestamp" in sample_text or re.search(r"\d{4}-\d{2}-\d{2}", sample_text):
            columns.insert(
                0,
                ColumnDefinition(name="timestamp", sql_type="TEXT", description="Detected timestamp value."),
            )

        if "error" in sample_text or "exception" in sample_text:
            columns.append(
                ColumnDefinition(name="error_code", sql_type="TEXT", description="Detected error code or identifier.")
            )

        return columns

    @staticmethod
    def _sanitize(name: str) -> str:
        return sanitize_identifier(name)
