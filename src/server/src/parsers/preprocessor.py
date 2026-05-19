from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from parsers.contracts import INGESTION_SCHEMA_VERSION, ClassificationResult, FileClassification, StructuralClass
from parsers.few_shot_store import FewShotStore
from parsers.profiles import LogProfileDefinition, get_profile
from parsers.schema_cache import SchemaCache

logger = logging.getLogger(__name__)

MAX_SAMPLE_LINES = 30
MAX_SAMPLE_RECORDS = 5
MAX_LINE_LENGTH = 2000

SCHEMA_VERSION = "1.0.0"


class ColumnKind(str, Enum):
    BASELINE = "baseline"
    DETECTED = "detected"
    LLM_INFERRED = "llm_inferred"


class SqlType(str, Enum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    REAL = "REAL"


class DetectedFormat(str, Enum):
    JSON_LINES = "json_lines"
    XML = "xml"
    CSV = "csv"
    SYSLOG = "syslog"
    APACHE_ACCESS = "apache_access"
    NGINX_ACCESS = "nginx_access"
    LOGFMT = "logfmt"
    KEY_VALUE = "key_value"
    BINARY_HEX = "binary_hex"
    SECTIONED_KV = "sectioned_kv"
    TIMESTAMPED_EVENT = "timestamped_event"
    PLAIN_TEXT = "plain_text"
    UNKNOWN = "unknown"


class SegmentationStrategy(str, Enum):
    PER_LINE = "per_line"
    PER_MULTILINE_CLUSTER = "per_multiline_cluster"
    PER_FILE = "per_file"
    MIXED = "mixed"


class InferredColumn(BaseModel):
    name: str
    sql_type: SqlType = SqlType.TEXT
    description: str = ""
    nullable: bool = True
    kind: ColumnKind = ColumnKind.DETECTED
    example_values: list[str] = Field(default_factory=list)


class SegmentationResult(BaseModel):
    strategy: SegmentationStrategy
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class FileObservation(BaseModel):
    filename: str
    line_count: int
    detected_format: DetectedFormat
    format_confidence: float = Field(ge=0.0, le=1.0)
    segmentation_hint: SegmentationStrategy
    sample_size: int
    warnings: list[str] = Field(default_factory=list)


class SampleRecord(BaseModel):
    source_file: str
    line_start: int
    line_end: int
    fields: dict[str, Any]


class FileInput(BaseModel):
    file_id: str | None = None
    filename: str
    content: str


SYSLOG_PATTERN = re.compile(
    r"^(<\d{1,3}>)?"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+"
    r"\S+\s+\S+",
    re.IGNORECASE,
)

APACHE_CLF_PATTERN = re.compile(
    r"^\S+\s+\S+\s+\S+\s+\[.+?\]\s+\".+?\"\s+\d{3}\s+\d+",
)

LOGFMT_PATTERN = re.compile(
    r"^(?:\w[\w.\-]*=(?:\"[^\"]*\"|\S+)\s*){2,}",
)

KEY_VALUE_PATTERN = re.compile(
    r"(?:\w[\w.\-]*\s*[:=]\s*(?:\"[^\"]*\"|\S+)\s*){2,}",
)

ISO_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}",
)

# Flexible timestamp pattern: matches YYYY-MM-DD, MM/DD/YYYY, DD/MM/YYYY
FLEXIBLE_TIMESTAMP_PATTERN = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[T ]|\d{2}[-/]\d{2}[-/]\d{4}\s+)\d{2}:\d{2}:\d{2}",
)

MULTILINE_CONTINUATION_PATTERN = re.compile(
    r"^(?:\s+at\s|Caused by:|\.{3}\s*\d+\s*more|\s{4,}\S)",
)

LOG_LEVEL_PATTERN = re.compile(
    r"\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL|NOTICE|ALERT|EMERG(?:ENCY)?)\b",
    re.IGNORECASE,
)

# Pattern for bracketed timestamps like [2026-04-17 08:03:15.441 UTC]
BRACKETED_TIMESTAMP_PATTERN = re.compile(
    r"^\[\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}:\d{2}",
)

# Pattern for Windows Event style "Key: Value" lines
COLON_SEPARATED_KV_PATTERN = re.compile(
    r"^[A-Za-z][\w\s]+\s*:\s*.+",
)

# Pattern for "KEY=VALUE" lines in sectioned blocks
EQUALS_KV_PATTERN = re.compile(
    r"^[A-Z][A-Z_\d]+\s*=\s*.+",
)

# Pattern for blank-line separated blocks (sectioned content)
SECTION_BOUNDARY_PATTERN = re.compile(r"^\s*$")


class LogPreprocessorService:
    def __init__(
        self,
        table_name: str = "logs",
        use_llm: bool = True,
        profile_name: str | None = None,
        schema_cache: SchemaCache | None = None,
        few_shot_store: FewShotStore | None = None,
    ) -> None:
        self.table_name = table_name
        self.use_llm = use_llm
        self.profile_name = (profile_name or "default").strip() or "default"
        self.profile: LogProfileDefinition = get_profile(self.profile_name)
        self.schema_cache = schema_cache or SchemaCache()
        self.few_shot_store = few_shot_store or FewShotStore()

    def classify(self, files: list[FileInput]) -> ClassificationResult:
        warnings: list[str] = []
        file_classifications: list[FileClassification] = []
        observations: list[FileObservation] = []
        diagnostics: dict[str, Any] = {
            "mode": "heuristic",
            "files": [],
            "profile": self.profile.model_dump(),
        }

        for file_input in files:
            lines = file_input.content.splitlines()
            if not lines:
                warnings.append(f"{file_input.filename}: file is empty, skipped.")
                file_classifications.append(
                    FileClassification(
                        file_id=file_input.file_id,
                        filename=file_input.filename,
                        detected_format=DetectedFormat.UNKNOWN.value,
                        structural_class=StructuralClass.UNSTRUCTURED,
                        format_confidence=0.0,
                        line_count=0,
                        warnings=["File is empty."],
                    )
                )
                continue

            sample = [line for line in lines[:50] if line.strip()]
            fingerprint = self._fingerprint(sample)
            cached = self.schema_cache.get_by_fingerprint(
                fingerprint=fingerprint,
                domain=self.profile.domain,
                profile_name=self.profile_name,
                min_confidence=self.profile.cache_confidence_threshold,
            )
            if cached is not None:
                cached_confidence = max(cached.format_confidence, self.profile.cache_confidence_threshold)
                cached_structural = self._normalize_structural_class(cached.structural_class)
                observations.append(
                    FileObservation(
                        filename=file_input.filename,
                        line_count=len(lines),
                        detected_format=DetectedFormat(cached.detected_format)
                        if cached.detected_format in {item.value for item in DetectedFormat}
                        else DetectedFormat.UNKNOWN,
                        format_confidence=round(min(cached_confidence, 1.0), 2),
                        segmentation_hint=SegmentationStrategy.PER_LINE,
                        sample_size=min(len(lines), MAX_SAMPLE_LINES),
                        warnings=[],
                    )
                )
                file_classifications.append(
                    FileClassification(
                        file_id=file_input.file_id,
                        filename=file_input.filename,
                        detected_format=cached.detected_format,
                        structural_class=cached_structural,
                        format_confidence=round(min(cached_confidence, 1.0), 2),
                        line_count=len(lines),
                        warnings=[],
                    )
                )
                diagnostics["files"].append(
                    {
                        "filename": file_input.filename,
                        "detected_format": cached.detected_format,
                        "format_confidence": round(min(cached_confidence, 1.0), 2),
                        "line_count": len(lines),
                        "segmentation": SegmentationStrategy.PER_LINE.value,
                        "source": "adaptive_cache",
                        "fingerprint": fingerprint,
                    }
                )
                self.schema_cache.record_success(cached.schema_key)
                continue

            detected_format, format_confidence = self._detect_format(lines)
            segmentation = self._detect_segmentation(lines, detected_format)
            structural_class = self._format_to_structural_class(detected_format, format_confidence)

            file_warnings: list[str] = []
            if format_confidence < 0.5:
                file_warnings.append(f"Low format confidence ({format_confidence:.2f}) results may be approximate.")

            observations.append(
                FileObservation(
                    filename=file_input.filename,
                    line_count=len(lines),
                    detected_format=detected_format,
                    format_confidence=format_confidence,
                    segmentation_hint=segmentation.strategy,
                    sample_size=min(len(lines), MAX_SAMPLE_LINES),
                    warnings=file_warnings,
                )
            )
            file_classifications.append(
                FileClassification(
                    file_id=file_input.file_id,
                    filename=file_input.filename,
                    detected_format=detected_format.value,
                    structural_class=structural_class,
                    format_confidence=format_confidence,
                    line_count=len(lines),
                    warnings=file_warnings,
                )
            )
            diagnostics["files"].append(
                {
                    "filename": file_input.filename,
                    "detected_format": detected_format.value,
                    "format_confidence": format_confidence,
                    "line_count": len(lines),
                    "segmentation": segmentation.strategy.value,
                    "source": "heuristic",
                    "fingerprint": fingerprint,
                }
            )

        dominant_format = self._dominant_format(observations)
        structural_class_overall = self._dominant_structural_class(file_classifications)
        selected_parser_key = self._select_parser_key(structural_class_overall, dominant_format.value)
        confidence = self._compute_confidence(observations)

        return ClassificationResult(
            schema_version=INGESTION_SCHEMA_VERSION,
            dominant_format=dominant_format.value,
            structural_class=structural_class_overall,
            selected_parser_key=selected_parser_key,
            file_classifications=file_classifications,
            warnings=warnings,
            confidence=confidence,
            diagnostics=diagnostics,
        )

    def classify_with_llm(self, files: list[FileInput]) -> ClassificationResult:
        heuristic_result = self.classify(files)
        if heuristic_result.confidence >= self.profile.llm_heuristic_fallback_threshold:
            return heuristic_result

        if not self.use_llm:
            return heuristic_result

        from parsers.llm_engine import LlmEngine

        llm_engine = LlmEngine(
            few_shot_store=self.few_shot_store,
            profile_definition=self.profile.model_dump(),
        )
        warnings = list(heuristic_result.warnings)
        file_classifications: list[FileClassification] = []
        diagnostics: dict[str, Any] = {
            "mode": "llm_hybrid",
            "files": [],
            "profile": self.profile.model_dump(),
        }

        for file_input in files:
            lines = file_input.content.splitlines()
            if not lines:
                file_classifications.append(
                    FileClassification(
                        file_id=file_input.file_id,
                        filename=file_input.filename,
                        detected_format=DetectedFormat.UNKNOWN.value,
                        structural_class=StructuralClass.UNSTRUCTURED,
                        format_confidence=0.0,
                        line_count=0,
                        warnings=["File is empty."],
                    )
                )
                continue

            file_classification = next(
                (fc for fc in heuristic_result.file_classifications if fc.file_id == file_input.file_id),
                None,
            )
            if file_classification and file_classification.format_confidence >= 0.7:
                file_classifications.append(file_classification)
                continue

            sample_lines = [line for line in lines[:30] if line.strip()]
            if not sample_lines:
                file_classifications.append(
                    FileClassification(
                        file_id=file_input.file_id,
                        filename=file_input.filename,
                        detected_format=DetectedFormat.UNKNOWN.value,
                        structural_class=StructuralClass.UNSTRUCTURED,
                        format_confidence=0.0,
                        line_count=len(lines),
                    )
                )
                continue

            fingerprint = self._fingerprint(sample_lines)
            few_shot_examples = self.few_shot_store.get_example_texts(
                format_name=(
                    file_classification.detected_format if file_classification else DetectedFormat.UNKNOWN.value
                ),
                domain=self.profile.domain,
                profile_name=self.profile_name,
                fingerprint=fingerprint,
                max_count=3,
            )

            llm_result = llm_engine.detect_format(
                sample_lines=sample_lines,
                few_shot_examples=few_shot_examples,
                profile_context=self.profile.model_dump(),
            )
            if llm_result.success and llm_result.response:
                response = llm_result.response
                structural_class = self._llm_category_to_structural_class(response.format_category)
                file_classifications.append(
                    FileClassification(
                        file_id=file_input.file_id,
                        filename=file_input.filename,
                        detected_format=response.format_name,
                        structural_class=structural_class,
                        format_confidence=response.confidence,
                        line_count=len(lines),
                        warnings=response.warnings,
                    )
                )
                logger.info(
                    "LLM detected format '%s' for '%s' (confidence: %.2f)",
                    response.format_name,
                    file_input.filename,
                    response.confidence,
                )
                diagnostics["files"].append(
                    {
                        "filename": file_input.filename,
                        "detected_format": response.format_name,
                        "format_confidence": response.confidence,
                        "source": "llm",
                        "fingerprint": fingerprint,
                    }
                )
            else:
                if file_classification:
                    file_classifications.append(file_classification)
                else:
                    file_classifications.append(
                        FileClassification(
                            file_id=file_input.file_id,
                            filename=file_input.filename,
                            detected_format=DetectedFormat.UNKNOWN.value,
                            structural_class=StructuralClass.UNSTRUCTURED,
                            format_confidence=0.0,
                            line_count=len(lines),
                            warnings=[llm_result.warning] if llm_result.warning else [],
                        )
                    )
                warnings.append(f"LLM format detection failed for '{file_input.filename}': {llm_result.warning}")
                diagnostics["files"].append(
                    {
                        "filename": file_input.filename,
                        "source": "heuristic_fallback",
                        "warning": llm_result.warning,
                    }
                )

        dominant_format = self._dominant_format_from_classifications(file_classifications)
        structural_class_overall = self._dominant_structural_class(file_classifications)
        selected_parser_key = self._select_parser_key(structural_class_overall, dominant_format)
        confidence = self._compute_confidence_from_classifications(file_classifications)

        return ClassificationResult(
            schema_version=INGESTION_SCHEMA_VERSION,
            dominant_format=dominant_format,
            structural_class=structural_class_overall,
            selected_parser_key=selected_parser_key,
            file_classifications=file_classifications,
            warnings=warnings,
            confidence=confidence,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _llm_category_to_structural_class(category: Any) -> StructuralClass:
        from parsers.llm_contracts import LogFormatCategory

        if category == LogFormatCategory.STRUCTURED:
            return StructuralClass.STRUCTURED
        if category == LogFormatCategory.SEMI_STRUCTURED:
            return StructuralClass.SEMI_STRUCTURED
        return StructuralClass.UNSTRUCTURED

    @staticmethod
    def _format_to_structural_class(fmt: DetectedFormat, confidence: float) -> StructuralClass:
        if fmt in {
            DetectedFormat.JSON_LINES,
            DetectedFormat.XML,
            DetectedFormat.CSV,
            DetectedFormat.SYSLOG,
            DetectedFormat.APACHE_ACCESS,
            DetectedFormat.NGINX_ACCESS,
            DetectedFormat.LOGFMT,
            DetectedFormat.BINARY_HEX,
            DetectedFormat.SECTIONED_KV,
            DetectedFormat.TIMESTAMPED_EVENT,
        }:
            return StructuralClass.STRUCTURED
        if fmt == DetectedFormat.KEY_VALUE:
            return StructuralClass.STRUCTURED if confidence >= 0.6 else StructuralClass.SEMI_STRUCTURED
        return StructuralClass.UNSTRUCTURED

    @staticmethod
    def _dominant_structural_class(file_classifications: list[FileClassification]) -> StructuralClass:
        if not file_classifications:
            return StructuralClass.UNSTRUCTURED

        counts: dict[StructuralClass, int] = {}
        for file_classification in file_classifications:
            counts[file_classification.structural_class] = counts.get(file_classification.structural_class, 0) + 1

        return max(counts, key=lambda item: counts[item])

    @staticmethod
    def _select_parser_key(structural_class: StructuralClass, detected_format: str) -> str:
        if structural_class == StructuralClass.UNSTRUCTURED:
            return "unified"

        parser_by_format = {
            DetectedFormat.JSON_LINES.value: "json_lines",
            DetectedFormat.XML.value: "xml",
            DetectedFormat.CSV.value: "csv",
            DetectedFormat.SYSLOG.value: "syslog",
            DetectedFormat.APACHE_ACCESS.value: "apache_access",
            DetectedFormat.NGINX_ACCESS.value: "nginx_access",
            DetectedFormat.LOGFMT.value: "logfmt",
            DetectedFormat.KEY_VALUE.value: "key_value",
            DetectedFormat.BINARY_HEX.value: "binary_hex",
            DetectedFormat.SECTIONED_KV.value: "sectioned_kv",
            DetectedFormat.TIMESTAMPED_EVENT.value: "timestamped_event",
        }
        return parser_by_format.get(detected_format, "unified")

    def _detect_format(self, lines: list[str]) -> tuple[DetectedFormat, float]:
        sample = [line for line in lines[:50] if line.strip()]
        if not sample:
            return DetectedFormat.UNKNOWN, 0.0

        full_content = "\n".join(lines).strip()

        try:
            from parsers.unified.fingerprint import FingerprintEngine

            fingerprint = FingerprintEngine().fingerprint(sample)
            mapped = self._map_fingerprint_format(fingerprint.format_name)
            if mapped is not None and fingerprint.confidence >= 0.85:
                # Validate JSON fingerprint to avoid bracketed non-JSON content
                if mapped == DetectedFormat.JSON_LINES:
                    if not self._is_json_document(full_content):
                        mapped = None
                if mapped is not None:
                    return mapped, round(min(fingerprint.confidence, 1.0), 2)
        except Exception as error:  # noqa: BLE001
            logger.debug("Fingerprint detection unavailable: %s", error)

        scores: dict[DetectedFormat, float] = {}

        if self._is_json_document(full_content):
            scores[DetectedFormat.JSON_LINES] = 0.98

        json_hits = sum(1 for line in sample if self._is_json_object(line))
        if json_hits > 0:
            scores[DetectedFormat.JSON_LINES] = max(scores.get(DetectedFormat.JSON_LINES, 0.0), json_hits / len(sample))

        xml_score = self._score_xml(sample)
        if xml_score > 0:
            scores[DetectedFormat.XML] = xml_score

        csv_score = self._score_csv(sample)
        if csv_score > 0:
            scores[DetectedFormat.CSV] = csv_score

        syslog_hits = sum(1 for line in sample if SYSLOG_PATTERN.match(line))
        if syslog_hits > 0:
            scores[DetectedFormat.SYSLOG] = syslog_hits / len(sample)

        clf_hits = sum(1 for line in sample if APACHE_CLF_PATTERN.match(line))
        if clf_hits > 0:
            has_nginx_markers = any("upstream" in line.lower() or "nginx" in line.lower() for line in sample)
            if has_nginx_markers:
                scores[DetectedFormat.NGINX_ACCESS] = clf_hits / len(sample)
            else:
                scores[DetectedFormat.APACHE_ACCESS] = clf_hits / len(sample)

        logfmt_hits = sum(1 for line in sample if LOGFMT_PATTERN.match(line))
        if logfmt_hits > 0:
            scores[DetectedFormat.LOGFMT] = logfmt_hits / len(sample)

        kv_hits = sum(1 for line in sample if KEY_VALUE_PATTERN.search(line))
        if kv_hits > 0 and DetectedFormat.LOGFMT not in scores:
            scores[DetectedFormat.KEY_VALUE] = kv_hits / len(sample) * 0.8

        # Sectioned KV: blank-line-delimited blocks of "Key: Value" or "KEY=VALUE" lines
        colon_kv_hits = sum(1 for line in sample if COLON_SEPARATED_KV_PATTERN.match(line))
        equals_kv_hits = sum(1 for line in sample if EQUALS_KV_PATTERN.match(line))
        blank_lines = sum(1 for line in lines[:50] if SECTION_BOUNDARY_PATTERN.match(line))
        total_kv_lines = colon_kv_hits + equals_kv_hits
        kv_ratio = total_kv_lines / max(len(sample), 1)
        if total_kv_lines >= 2 and blank_lines >= 2 and kv_ratio >= 0.3:
            sectioned_score = min(0.85, kv_ratio * 1.2)
            scores[DetectedFormat.SECTIONED_KV] = sectioned_score
            # Sectioned KV is more specific than generic key_value
            scores.pop(DetectedFormat.KEY_VALUE, None)
            # Only override timestamped event if KV lines dominate
            if kv_ratio >= 0.5:
                scores.pop(DetectedFormat.TIMESTAMPED_EVENT, None)

        # Timestamped event text: lines starting with bracketed or ISO timestamps
        # Don't detect as timestamped event if CSV/TSV is already detected
        if DetectedFormat.CSV not in scores:
            bracketed_ts_hits = sum(1 for line in sample if BRACKETED_TIMESTAMP_PATTERN.match(line))
            iso_ts_hits = sum(1 for line in sample if ISO_TIMESTAMP_PATTERN.match(line))
            flex_ts_hits = sum(1 for line in sample if FLEXIBLE_TIMESTAMP_PATTERN.match(line))
            any_ts_hits = bracketed_ts_hits + iso_ts_hits + flex_ts_hits
            if (
                any_ts_hits > 0
                and DetectedFormat.SECTIONED_KV not in scores
                and DetectedFormat.JSON_LINES not in scores
            ):
                ts_score = any_ts_hits / len(sample)
                # Check for multiline continuation patterns
                continuation_hits = sum(1 for line in sample if MULTILINE_CONTINUATION_PATTERN.match(line))
                if continuation_hits > 0:
                    ts_score = min(1.0, ts_score + continuation_hits / len(sample) * 0.3)
                scores[DetectedFormat.TIMESTAMPED_EVENT] = ts_score
                # Remove conflicting generic formats
                scores.pop(DetectedFormat.PLAIN_TEXT, None)

        # Binary/hex detection via content (hex dump with consecutive hex pairs)
        if not scores.get(DetectedFormat.BINARY_HEX):
            hex_dump_hits = sum(1 for line in sample[:10] if re.search(r"(?:[0-9a-fA-F]{2}[ :.\t]){5,}", line))
            if hex_dump_hits >= 3:
                scores[DetectedFormat.BINARY_HEX] = 0.85

        # Binary content detection (e.g. .bin files read with errors='replace')
        if DetectedFormat.BINARY_HEX not in scores and len(lines) >= 1:
            sample_text = "\n".join(lines[:10])
            # Check for null bytes (strong indicator of binary content)
            if "\x00" in sample_text:
                scores[DetectedFormat.BINARY_HEX] = 0.85
            else:
                try:
                    import chardet

                    raw_bytes = sample_text.encode("utf-8", errors="replace")
                    result = chardet.detect(raw_bytes)
                    if result and result.get("encoding") in ("binary", None) and result.get("confidence", 0) > 0.7:
                        scores[DetectedFormat.BINARY_HEX] = 0.85
                except ImportError:
                    pass
                except Exception:
                    pass

        # XML should win over key_value when XML is confidently detected
        if DetectedFormat.XML in scores and scores[DetectedFormat.XML] >= 0.8:
            scores.pop(DetectedFormat.KEY_VALUE, None)

        if not scores:
            return DetectedFormat.PLAIN_TEXT, 0.3

        best_format = max(scores, key=lambda key: scores[key])
        return best_format, round(min(scores[best_format], 1.0), 2)

    @staticmethod
    def _map_fingerprint_format(format_name: str) -> DetectedFormat | None:
        mapping = {
            "json_lines": DetectedFormat.JSON_LINES,
            "json_document": DetectedFormat.JSON_LINES,
            "xml": DetectedFormat.XML,
            "csv": DetectedFormat.CSV,
            "syslog": DetectedFormat.SYSLOG,
            "apache_clf": DetectedFormat.APACHE_ACCESS,
            "logfmt": DetectedFormat.LOGFMT,
            "key_value": DetectedFormat.KEY_VALUE,
            "section_delimited": DetectedFormat.KEY_VALUE,
            "hex_dump": DetectedFormat.BINARY_HEX,
            "plain_text": DetectedFormat.PLAIN_TEXT,
        }
        return mapping.get(format_name)

    def _detect_segmentation(self, lines: list[str], detected_format: DetectedFormat) -> SegmentationResult:
        if detected_format == DetectedFormat.XML:
            return SegmentationResult(
                strategy=SegmentationStrategy.PER_FILE,
                confidence=0.9,
                rationale="XML payload is parsed as a whole document before row extraction.",
            )

        if len(lines) <= 3 and detected_format in (DetectedFormat.PLAIN_TEXT, DetectedFormat.UNKNOWN):
            return SegmentationResult(
                strategy=SegmentationStrategy.PER_FILE,
                confidence=0.7,
                rationale="Very short unstructured file treated as one record.",
            )

        continuation_count = sum(1 for line in lines if MULTILINE_CONTINUATION_PATTERN.match(line))
        continuation_ratio = continuation_count / len(lines) if lines else 0.0
        if continuation_ratio > 0.15:
            return SegmentationResult(
                strategy=SegmentationStrategy.PER_MULTILINE_CLUSTER,
                confidence=round(min(0.6 + continuation_ratio, 0.95), 2),
                rationale=f"{continuation_count}/{len(lines)} lines match multiline continuation patterns.",
            )

        return SegmentationResult(
            strategy=SegmentationStrategy.PER_LINE,
            confidence=0.9,
            rationale=f"Defaulted to line segmentation for format '{detected_format.value}'.",
        )

    @staticmethod
    def _compute_confidence(observations: list[FileObservation]) -> float:
        if not observations:
            return 0.0

        average_format_confidence = sum(observation.format_confidence for observation in observations) / len(
            observations
        )
        base = average_format_confidence

        total_warnings = sum(len(observation.warnings) for observation in observations)
        if total_warnings > 0:
            base -= min(total_warnings * 0.05, 0.2)

        return round(max(0.0, min(base, 1.0)), 2)

    @staticmethod
    def _dominant_format(observations: list[FileObservation]) -> DetectedFormat:
        if not observations:
            return DetectedFormat.UNKNOWN

        format_counts: dict[DetectedFormat, int] = {}
        for observation in observations:
            format_counts[observation.detected_format] = format_counts.get(observation.detected_format, 0) + 1
        return max(format_counts, key=lambda detected_format: format_counts[detected_format])

    @staticmethod
    def _is_json_object(line: str) -> bool:
        stripped = line.strip()
        if not stripped.startswith("{"):
            return False
        try:
            parsed = json.loads(stripped)
            return isinstance(parsed, dict)
        except (json.JSONDecodeError, ValueError):
            return False

    @staticmethod
    def _score_xml(lines: list[str]) -> float:
        document = "\n".join(lines).strip()
        if not document.startswith("<"):
            return 0.0
        # Try full parse first
        try:
            ET.fromstring(document)
            return 0.98
        except ET.ParseError:
            pass
        # For truncated XML (e.g. sampled first N lines), try partial parse
        # by checking if a significant portion of lines look like XML tags
        xml_tag_re = re.compile(r"^\s*(?:<\?xml|<[\w:!?])")
        xml_lines = sum(1 for line in lines if xml_tag_re.match(line))
        if len(lines) > 0 and xml_lines / len(lines) >= 0.6:
            return 0.85
        return 0.0

    @staticmethod
    def _score_csv(sample: list[str]) -> float:
        if len(sample) < 2:
            return 0.0

        best_score = 0.0
        for delimiter in [",", "\t", "|", ";"]:
            header = sample[0]
            if delimiter not in header:
                continue

            expected_columns = header.count(delimiter) + 1
            if expected_columns < 2:
                continue

            matching = 0
            data_sample = sample[1:10]
            for line in data_sample:
                actual_columns = line.count(delimiter) + 1
                if actual_columns == expected_columns:
                    matching += 1

            if not data_sample:
                continue

            score = matching / len(data_sample)
            if score > best_score:
                best_score = score

        return best_score

    @staticmethod
    def _is_json_document(content: str) -> bool:
        if not content:
            return False
        stripped = content.strip()
        if not stripped or stripped[0] not in {"{", "["}:
            return False
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            return False
        return isinstance(parsed, (dict, list))

    @staticmethod
    def _dominant_format_from_classifications(
        file_classifications: list[FileClassification],
    ) -> str:
        if not file_classifications:
            return DetectedFormat.UNKNOWN.value

        format_counts: dict[str, int] = {}
        for fc in file_classifications:
            format_counts[fc.detected_format] = format_counts.get(fc.detected_format, 0) + 1
        return max(format_counts, key=lambda fmt: format_counts[fmt])

    @staticmethod
    def _compute_confidence_from_classifications(
        file_classifications: list[FileClassification],
    ) -> float:
        if not file_classifications:
            return 0.0

        average_confidence = sum(fc.format_confidence for fc in file_classifications) / len(file_classifications)
        total_warnings = sum(len(fc.warnings) for fc in file_classifications)
        base = average_confidence
        if total_warnings > 0:
            base -= min(total_warnings * 0.05, 0.2)

        return round(max(0.0, min(base, 1.0)), 2)

    @staticmethod
    def _fingerprint(sample_lines: list[str]) -> str:
        if not sample_lines:
            return "empty"
        try:
            from parsers.unified.fingerprint import FingerprintEngine

            return FingerprintEngine().fingerprint(sample_lines).fingerprint
        except Exception:
            content = "\n".join(sample_lines[:20])
            return str(abs(hash(content)))

    @staticmethod
    def _normalize_structural_class(value: str) -> StructuralClass:
        normalized = (value or "").strip().lower()
        if normalized == StructuralClass.STRUCTURED.value:
            return StructuralClass.STRUCTURED
        if normalized == StructuralClass.SEMI_STRUCTURED.value:
            return StructuralClass.SEMI_STRUCTURED
        if normalized == StructuralClass.BINARY.value:
            return StructuralClass.BINARY
        return StructuralClass.UNSTRUCTURED
