from __future__ import annotations

import binascii
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import chardet
except ImportError:
    chardet = None

# Re-use patterns from preprocessor
try:
    from parsers.preprocessor import MULTILINE_CONTINUATION_PATTERN
except ImportError:
    # Fallback definition if preprocessor can't be imported
    import re as _re

    MULTILINE_CONTINUATION_PATTERN = _re.compile(
        r"^(?:\s+at\s|Caused by:|\.{3}\s*\d+\s*more|\s{4,}\S)",
    )

from parsers.contracts import (
    BASELINE_COLUMN_NAMES,
    BASELINE_COLUMNS,
    ColumnDefinition,
    ParserPipelineResult,
    ParserSupportRequest,
    ParserSupportResult,
    TableDefinition,
    build_ddl,
    make_display_name,
    make_megabase_table_name,
)
from parsers.normalization import coerce_scalar, sanitize_identifier, unique_identifier
from parsers.quality import evaluate_structured_parse_quality
from parsers.registry import ParserPipeline

APACHE_ACCESS_RE = re.compile(
    r"^(?P<ip>\S+)\s+(?P<ident>\S+)\s+(?P<authuser>\S+)\s+\[(?P<timestamp>[^\]]+)\]\s+\"(?P<request>[^\"]*)\"\s+(?P<status>\d{3})\s+(?P<body_bytes>\S+)(?:\s+\"(?P<referer>[^\"]*)\"\s+\"(?P<user_agent>[^\"]*)\")?"
)
SYSLOG_RE = re.compile(
    r"^(?:<(?P<pri>\d{1,3})>)?"
    r"(?P<timestamp>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<process>[\w.\-/]+)(?:\[(?P<pid>\d+)\])?:\s*(?P<message>.*)$",
    re.IGNORECASE,
)
LOGFMT_RE = re.compile(r"(\w[\w.\-]*)=(\"[^\"]*\"|\S+)")
KEY_VALUE_RE = re.compile(r"(\w[\w.\-]*)\s*[:=]\s*(\"[^\"]*\"|\S+)")
NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


@dataclass
class TableRelationship:
    parent_logical_name: str
    parent_key: str
    child_key: str
    relationship_type: str = "one_to_many"


@dataclass
class ParsedTable:
    logical_name: str
    rows: list[dict[str, Any]]
    required_columns: list[str] = field(default_factory=list)
    optional_columns: list[str] = field(default_factory=list)
    include_traceability_columns: bool = True
    relationships: list[TableRelationship] = field(default_factory=list)


class DeterministicParserPipeline(ParserPipeline):
    parser_key: str = ""
    supported_extensions: tuple[str, ...] = tuple()
    structured_output: bool = False

    def supports(self, request: ParserSupportRequest) -> ParserSupportResult:
        lower_name = request.filename.lower()
        if self.supported_extensions and any(lower_name.endswith(ext) for ext in self.supported_extensions):
            return ParserSupportResult(
                parser_key=self.parser_key,
                supported=True,
                score=0.95,
                reasons=["File extension strongly matches parser."],
            )

        score = self._score_content(request.content)
        return ParserSupportResult(
            parser_key=self.parser_key,
            supported=score >= 0.6,
            score=round(score, 2),
            reasons=["Deterministic parser content scoring."],
        )

    def parse(self, file_inputs: list[Any], classification: Any) -> ParserPipelineResult:
        table_definitions: list[TableDefinition] = []
        records: dict[str, list[dict[str, Any]]] = {}
        warnings: list[str] = []
        table_metadata: dict[str, dict[str, Any]] = {}
        required_columns_by_table: dict[str, list[str]] = {}
        optional_columns_by_table: dict[str, list[str]] = {}
        relationship_specs: list[dict[str, str]] = []
        parser_traceability_fields: set[str] = set()

        for file_input in file_inputs:
            parsed_tables, parse_warnings = self._parse_file(file_input.content, file_input.filename)
            warnings.extend(f"{file_input.filename}: {warning}" for warning in parse_warnings)
            if not parsed_tables:
                warnings.append(f"{file_input.filename}: no rows were extracted by parser '{self.parser_key}'.")
                continue

            logical_to_table_name: dict[str, str] = {}
            for parsed_table in parsed_tables:
                if not parsed_table.rows:
                    warnings.append(
                        f"{file_input.filename}: table '{parsed_table.logical_name}' had no extractable rows."
                    )
                    continue

                normalized_rows = [self._normalize_row(row) for row in parsed_table.rows]
                table_name = make_megabase_table_name()
                display_name = make_display_name(self.parser_key, file_input.file_id, file_input.filename)
                logical_to_table_name[parsed_table.logical_name] = table_name

                columns = self._infer_columns(
                    normalized_rows,
                    include_traceability=parsed_table.include_traceability_columns,
                    required_columns=parsed_table.required_columns,
                )
                ddl = build_ddl(table_name, columns)
                table_definitions.append(
                    TableDefinition(table_name=table_name, display_name=display_name, columns=columns, ddl=ddl)
                )
                records[table_name] = normalized_rows
                table_metadata[table_name] = {
                    "logical_name": parsed_table.logical_name,
                    "required_columns": parsed_table.required_columns,
                    "optional_columns": parsed_table.optional_columns,
                    "source_file": file_input.filename,
                }
                required_columns_by_table[table_name] = parsed_table.required_columns
                optional_columns_by_table[table_name] = parsed_table.optional_columns

                if parsed_table.include_traceability_columns:
                    parser_traceability_fields.update({"source", "raw", "message", "log_level"})

            for parsed_table in parsed_tables:
                child_table_name = logical_to_table_name.get(parsed_table.logical_name)
                if child_table_name is None:
                    continue
                for relationship in parsed_table.relationships:
                    parent_table_name = logical_to_table_name.get(relationship.parent_logical_name)
                    if parent_table_name is None:
                        continue
                    relationship_specs.append(
                        {
                            "parent_table": parent_table_name,
                            "child_table": child_table_name,
                            "parent_key": relationship.parent_key,
                            "child_key": relationship.child_key,
                            "type": relationship.relationship_type,
                        }
                    )

        confidence = 0.95 if table_definitions else 0.0
        validation_warnings: list[str] = []
        quality_gate_failed = False
        failed_tables: list[str] = []
        per_column_null_ratios: dict[str, dict[str, float]] = {}
        per_table_null_ratios: dict[str, float] = {}
        confidence_penalty = 0.0

        if table_definitions and self.structured_output:
            quality_report = evaluate_structured_parse_quality(
                records_by_table=records,
                required_columns_by_table=required_columns_by_table,
                optional_columns_by_table=optional_columns_by_table,
                traceability_fields=parser_traceability_fields,
            )
            validation_warnings = quality_report.validation_warnings
            failed_tables = quality_report.failed_tables
            quality_gate_failed = quality_report.should_fallback
            confidence_penalty = quality_report.confidence_penalty
            warnings.extend(validation_warnings)

            for table_name, table_report in quality_report.table_reports.items():
                per_column_null_ratios[table_name] = table_report.column_null_ratios
                per_table_null_ratios[table_name] = table_report.table_null_ratio

            confidence = max(0.05, 0.95 - confidence_penalty)
            if quality_gate_failed:
                confidence = min(confidence, 0.25)

        elif table_definitions:
            for table_name, rows in records.items():
                ratios = _compute_null_ratios_for_rows(rows)
                per_column_null_ratios[table_name] = ratios
                per_table_null_ratios[table_name] = 0.0

        return ParserPipelineResult(
            table_definitions=table_definitions,
            records=records,
            parser_key=self.parser_key,
            warnings=warnings,
            confidence=round(confidence, 2),
            diagnostics={
                "mode": "deterministic",
                "parser_key": self.parser_key,
                "input_files": len(file_inputs),
                "classified_format": getattr(classification, "dominant_format", "unknown"),
                "table_metadata": table_metadata,
                "relationships": relationship_specs,
                "table_row_counts": {table_name: len(rows) for table_name, rows in records.items()},
                "per_column_null_ratios": per_column_null_ratios,
                "per_table_null_ratios": per_table_null_ratios,
                "validation_warnings": validation_warnings,
                "quality_gate_failed": quality_gate_failed,
                "failed_tables": failed_tables,
                "confidence_penalty": round(confidence_penalty, 3),
            },
        )

    def _score_content(self, content: str) -> float:
        return 0.6

    def _parse_file(self, content: str, filename: str) -> tuple[list[ParsedTable], list[str]]:
        rows, warnings = self._parse_rows(content, filename)
        if not rows:
            fallback_rows: list[dict[str, Any]] = []
            for line in content.splitlines():
                stripped_line = line.strip()
                if not stripped_line:
                    continue
                fallback_rows.append(
                    {
                        "source_file": filename,
                        "raw": stripped_line,
                        "message": stripped_line[:500],
                        "log_level": _infer_log_level(stripped_line),
                    }
                )

            if fallback_rows:
                warnings.append("No JSON objects were found; treating content as line-oriented text.")
                return (
                    [
                        ParsedTable(
                            logical_name=_logical_name_from_filename(filename),
                            rows=fallback_rows,
                            required_columns=["message"],
                            include_traceability_columns=False,
                        )
                    ],
                    warnings,
                )

            return [], warnings
        return [ParsedTable(logical_name=_logical_name_from_filename(filename), rows=rows)], warnings

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        raise NotImplementedError

    def _infer_columns(
        self,
        rows: list[dict[str, Any]],
        include_traceability: bool,
        required_columns: list[str] | None = None,
    ) -> list[ColumnDefinition]:
        merged: list[ColumnDefinition] = []
        required = set(required_columns or [])

        if include_traceability:
            merged.extend(list(BASELINE_COLUMNS))
            merged.extend(
                [
                    ColumnDefinition(name="source", sql_type="TEXT", description="Source filename.", nullable=True),
                    ColumnDefinition(
                        name="message", sql_type="TEXT", description="Primary message text.", nullable=True
                    ),
                    ColumnDefinition(
                        name="log_level", sql_type="TEXT", description="Detected log level.", nullable=True
                    ),
                ]
            )

        existing = {column.name for column in merged}

        key_types: dict[str, set[str]] = {}
        for row in rows:
            for key, value in row.items():
                if key in BASELINE_COLUMN_NAMES or key in {"source", "message", "log_level"}:
                    continue
                key_types.setdefault(key, set()).add(_infer_sql_type(value))

        for key in sorted(key_types.keys()):
            if key in existing:
                continue
            sql_type = _merge_sql_types(key_types[key])
            merged.append(
                ColumnDefinition(
                    name=key,
                    sql_type=sql_type,
                    description=f"Extracted field '{key}'.",
                    nullable=key not in required,
                )
            )

        return merged

    @staticmethod
    def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            safe_key = _sanitize(key)
            normalized[safe_key] = value
        return normalized


class JsonLinesPipeline(DeterministicParserPipeline):
    parser_key = "json_lines"
    supported_extensions = (".json", ".jsonl", ".ndjson")
    structured_output = True

    def _score_content(self, content: str) -> float:
        stripped = content.strip()
        if not stripped:
            return 0.0
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return 0.98
        except (json.JSONDecodeError, ValueError):
            pass

        lines = [line.strip() for line in content.splitlines()[:25] if line.strip()]
        hits = sum(1 for line in lines if line.startswith("{") and line.endswith("}"))
        return hits / max(len(lines), 1)

    def _parse_file(self, content: str, filename: str) -> tuple[list[ParsedTable], list[str]]:
        warnings: list[str] = []
        stripped = content.strip()
        if not stripped:
            return [], warnings

        try:
            parsed = json.loads(stripped)
            return self._parse_json_document(parsed, filename), warnings
        except (json.JSONDecodeError, ValueError):
            warnings.append("Unable to parse as JSON document; attempting line-delimited JSON fallback.")

        rows: list[dict[str, Any]] = []
        for index, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                warnings.append(f"line {index}: invalid JSON object")
                continue
            if not isinstance(parsed, dict):
                warnings.append(f"line {index}: JSON value is not an object")
                continue
            row = {"source_file": filename}
            row.update(_flatten_json(parsed))
            rows.append(row)

        if not rows:
            fallback_rows: list[dict[str, Any]] = []
            for line in content.splitlines():
                stripped_line = line.strip()
                if not stripped_line:
                    continue
                fallback_rows.append(
                    {
                        "source_file": filename,
                        "raw": stripped_line,
                        "message": stripped_line[:500],
                        "log_level": _infer_log_level(stripped_line),
                    }
                )

            if fallback_rows:
                warnings.append("No JSON objects were found; treating content as line-oriented text.")
                return (
                    [
                        ParsedTable(
                            logical_name=_logical_name_from_filename(filename),
                            rows=fallback_rows,
                            required_columns=["message"],
                            include_traceability_columns=False,
                        )
                    ],
                    warnings,
                )

            return [], warnings

        required_columns = [
            column for column in ("source_file", "timestamp", "message") if any(column in r for r in rows)
        ]
        return [
            ParsedTable(
                logical_name="json_records",
                rows=rows,
                required_columns=required_columns,
                include_traceability_columns=False,
            )
        ], warnings

    def _parse_json_document(self, payload: Any, filename: str) -> list[ParsedTable]:
        if isinstance(payload, list):
            return self._parse_json_list(payload, filename)
        if isinstance(payload, dict):
            return self._parse_json_object(payload, filename)
        return []

    def _parse_json_list(self, payload: list[Any], filename: str) -> list[ParsedTable]:
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            row = {"source_file": filename, "document_id": f"{_stable_hash(filename)}_{index}"}
            row.update(_flatten_json_scalars(item))
            rows.append(row)

        if not rows:
            return []

        required = [column for column in ("document_id", "source_file") if column in rows[0]]
        return [
            ParsedTable(
                logical_name="records",
                rows=rows,
                required_columns=required,
                include_traceability_columns=False,
            )
        ]

    def _parse_json_object(self, payload: dict[str, Any], filename: str) -> list[ParsedTable]:
        parent_logical_name = "run"
        document_id = str(payload.get("run_id") or f"{_stable_hash(filename)}_1")
        parent_row: dict[str, Any] = {
            "document_id": document_id,
            "source_file": filename,
        }
        tables: list[ParsedTable] = []
        child_tables: dict[str, list[dict[str, Any]]] = {}
        count_field_map = {
            "chambers": "chamber_count",
            "wafers": "wafer_count",
            "steps": "step_count",
            "alarms": "alarm_count",
        }

        for raw_key, raw_value in payload.items():
            key = _sanitize(raw_key)
            if isinstance(raw_value, dict):
                if key == "result":
                    for result_key, result_value in raw_value.items():
                        safe_result_key = _sanitize(result_key)
                        if safe_result_key == "status":
                            parent_row["result_status"] = _coerce_scalar(result_value)
                        else:
                            parent_row[safe_result_key] = _coerce_scalar(result_value)
                else:
                    parent_row.update({f"{key}_{k}": v for k, v in _flatten_json_scalars(raw_value).items()})
                continue

            if isinstance(raw_value, list):
                count_key = count_field_map.get(key, f"{key}_count")
                parent_row[count_key] = len(raw_value)

                if not raw_value:
                    continue

                if all(_is_scalar(item) for item in raw_value):
                    parent_row[key] = ",".join(str(_coerce_scalar(item)) for item in raw_value)
                    continue

                if all(isinstance(item, dict) for item in raw_value):
                    child_rows: list[dict[str, Any]] = []
                    for index, item in enumerate(raw_value, start=1):
                        row = {
                            "document_id": document_id,
                            "item_index": index,
                        }
                        row.update(_flatten_json_scalars(item))
                        if "run_id" in parent_row and "run_id" not in row:
                            row["run_id"] = parent_row["run_id"]
                        child_rows.append(row)
                    child_tables[key] = child_rows
                    continue

                parent_row[key] = json.dumps(raw_value, ensure_ascii=True)
                continue

            parent_row[key] = _coerce_scalar(raw_value)

        parent_required = [
            column
            for column in (
                "document_id",
                "tool_id",
                "run_id",
                "lot_id",
                "recipe",
                "start_ts",
                "end_ts",
                "wafer_count",
                "step_count",
                "alarm_count",
                "result_status",
                "film_uniformity_pct",
                "avg_final_thickness_nm",
                "released_to_metrology",
            )
            if column in parent_row
        ]

        tables.append(
            ParsedTable(
                logical_name=parent_logical_name,
                rows=[parent_row],
                required_columns=parent_required,
                include_traceability_columns=False,
            )
        )

        for logical_name, rows in child_tables.items():
            required_columns = [column for column in ("document_id", "item_index") if rows and column in rows[0]]
            tables.append(
                ParsedTable(
                    logical_name=logical_name,
                    rows=rows,
                    required_columns=required_columns,
                    include_traceability_columns=False,
                    relationships=[
                        TableRelationship(
                            parent_logical_name=parent_logical_name,
                            parent_key="document_id",
                            child_key="document_id",
                        )
                    ],
                )
            )

        return tables

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        # The JSON parser handles multi-table normalization in _parse_file.
        return [], []


class CsvPipeline(DeterministicParserPipeline):
    parser_key = "csv"
    supported_extensions = (".csv", ".tsv")
    structured_output = True

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines() if line.strip()]
        if len(lines) < 2:
            return 0.0

        hex_dump_lines = sum(1 for line in lines[:10] if HEX_DUMP_LINE_RE.match(line))
        if hex_dump_lines >= 3:
            return 0.0

        delimiter = _sniff_delimiter(lines)
        if delimiter is None:
            return 0.0

        expected_columns = len(next(csv.reader([lines[0]], delimiter=delimiter)))
        if expected_columns < 2:
            return 0.0

        matching = 0
        checked = 0
        for line in lines[1:10]:
            checked += 1
            columns = len(next(csv.reader([line], delimiter=delimiter)))
            if columns == expected_columns:
                matching += 1

        if checked == 0:
            return 0.0
        return matching / checked

    def _parse_file(self, content: str, filename: str) -> tuple[list[ParsedTable], list[str]]:
        warnings: list[str] = []
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            return [], warnings

        delimiter = _sniff_delimiter(lines)
        if delimiter is None:
            warnings.append("Could not determine delimiter from input.")
            return [], warnings

        has_header = _detect_header(lines, delimiter)
        header_rows, header_columns = _parse_delimited_rows(
            lines=lines,
            delimiter=delimiter,
            has_header=has_header,
            filename=filename,
        )

        if not has_header:
            no_header_rows, no_header_columns = _parse_delimited_rows(
                lines=lines,
                delimiter=delimiter,
                has_header=False,
                filename=filename,
            )
            if _tabular_quality_score(no_header_rows, no_header_columns) > _tabular_quality_score(
                header_rows, header_columns
            ):
                header_rows, header_columns = no_header_rows, no_header_columns

        required_columns = [column for column in header_columns if column != "source_file"]
        return [
            ParsedTable(
                logical_name=_logical_name_from_filename(filename),
                rows=header_rows,
                required_columns=required_columns,
                include_traceability_columns=False,
            )
        ], warnings

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        # The CSV parser handles deterministic table projection in _parse_file.
        return [], []


class XmlPipeline(DeterministicParserPipeline):
    parser_key = "xml"
    supported_extensions = (".xml",)
    structured_output = True

    def _score_content(self, content: str) -> float:
        stripped = content.strip()
        if not stripped.startswith("<"):
            return 0.0
        try:
            ET.fromstring(stripped)
            return 0.98
        except ET.ParseError:
            return 0.0

    def _parse_file(self, content: str, filename: str) -> tuple[list[ParsedTable], list[str]]:
        warnings: list[str] = []
        stripped = content.strip()
        if not stripped:
            return [], warnings

        try:
            root = ET.fromstring(stripped)
        except ET.ParseError as error:
            warnings.append(f"Invalid XML document: {error}")
            return [], warnings

        if _sanitize(root.tag) == "recipe":
            return self._parse_recipe_xml(root, filename), warnings
        return self._parse_generic_xml(root, filename), warnings

    def _parse_recipe_xml(self, root: ET.Element, filename: str) -> list[ParsedTable]:
        recipe_name = root.attrib.get("name", "")
        recipe_version = root.attrib.get("version", "")
        recipe_id = f"{recipe_name}:{recipe_version}" if recipe_name else _stable_hash(filename)

        recipe_row: dict[str, Any] = {
            "source_file": filename,
            "recipe_id": recipe_id,
            "tool": root.attrib.get("tool"),
            "chamber": root.attrib.get("chamber"),
            "recipe_name": recipe_name or None,
            "version": recipe_version or None,
            "author": root.attrib.get("author"),
        }

        metadata = root.find("metadata")
        if metadata is not None:
            recipe_row["created_ts"] = _coerce_scalar(metadata.attrib.get("created_ts"))
            recipe_row["approved_by"] = metadata.attrib.get("approved_by")
            recipe_row["product"] = metadata.attrib.get("product")

        step_rows: list[dict[str, Any]] = []
        setpoint_rows: list[dict[str, Any]] = []
        interlock_rows: list[dict[str, Any]] = []
        tolerance_rows: list[dict[str, Any]] = []

        for step in root.findall("step"):
            step_seq = _coerce_scalar(step.attrib.get("seq"))
            step_row = {
                "recipe_id": recipe_id,
                "step_seq": step_seq,
                "step_name": step.attrib.get("name"),
                "duration_s": _coerce_scalar(step.attrib.get("duration_s")),
            }
            step_rows.append(step_row)

            for setpoint in step.findall("setpoint"):
                setpoint_rows.append(
                    {
                        "recipe_id": recipe_id,
                        "step_seq": step_seq,
                        "setpoint_name": setpoint.attrib.get("name"),
                        "setpoint_value": _coerce_scalar(setpoint.attrib.get("value")),
                    }
                )

            for interlock in step.findall("interlock"):
                interlock_rows.append(
                    {
                        "recipe_id": recipe_id,
                        "step_seq": step_seq,
                        "interlock_name": interlock.attrib.get("name"),
                        "interlock_required": _coerce_scalar(interlock.attrib.get("required")),
                    }
                )

            for tolerance in step.findall("tolerance"):
                tolerance_rows.append(
                    {
                        "recipe_id": recipe_id,
                        "step_seq": step_seq,
                        "tolerance_name": tolerance.attrib.get("name"),
                        "tolerance_low": _coerce_scalar(tolerance.attrib.get("low")),
                        "tolerance_high": _coerce_scalar(tolerance.attrib.get("high")),
                    }
                )

        tables: list[ParsedTable] = [
            ParsedTable(
                logical_name="recipe",
                rows=[recipe_row],
                required_columns=[
                    column
                    for column in ("recipe_id", "tool", "chamber", "recipe_name", "version", "author")
                    if recipe_row.get(column) is not None
                ],
                include_traceability_columns=False,
            )
        ]

        if step_rows:
            tables.append(
                ParsedTable(
                    logical_name="recipe_steps",
                    rows=step_rows,
                    required_columns=["recipe_id", "step_seq", "step_name", "duration_s"],
                    include_traceability_columns=False,
                    relationships=[
                        TableRelationship(parent_logical_name="recipe", parent_key="recipe_id", child_key="recipe_id")
                    ],
                )
            )

        if setpoint_rows:
            tables.append(
                ParsedTable(
                    logical_name="recipe_setpoints",
                    rows=setpoint_rows,
                    required_columns=["recipe_id", "step_seq", "setpoint_name", "setpoint_value"],
                    include_traceability_columns=False,
                    relationships=[
                        TableRelationship(
                            parent_logical_name="recipe_steps", parent_key="step_seq", child_key="step_seq"
                        ),
                        TableRelationship(parent_logical_name="recipe", parent_key="recipe_id", child_key="recipe_id"),
                    ],
                )
            )

        if interlock_rows:
            tables.append(
                ParsedTable(
                    logical_name="recipe_interlocks",
                    rows=interlock_rows,
                    required_columns=["recipe_id", "step_seq", "interlock_name", "interlock_required"],
                    include_traceability_columns=False,
                    relationships=[
                        TableRelationship(
                            parent_logical_name="recipe_steps", parent_key="step_seq", child_key="step_seq"
                        ),
                        TableRelationship(parent_logical_name="recipe", parent_key="recipe_id", child_key="recipe_id"),
                    ],
                )
            )

        if tolerance_rows:
            tables.append(
                ParsedTable(
                    logical_name="recipe_tolerances",
                    rows=tolerance_rows,
                    required_columns=["recipe_id", "step_seq", "tolerance_name", "tolerance_low", "tolerance_high"],
                    include_traceability_columns=False,
                    relationships=[
                        TableRelationship(
                            parent_logical_name="recipe_steps", parent_key="step_seq", child_key="step_seq"
                        ),
                        TableRelationship(parent_logical_name="recipe", parent_key="recipe_id", child_key="recipe_id"),
                    ],
                )
            )

        return tables

    def _parse_generic_xml(self, root: ET.Element, filename: str) -> list[ParsedTable]:
        document_id = _stable_hash(filename)
        context: dict[str, Any] = {"source_file": filename, "document_id": document_id}
        return self._build_tables_from_element(root, context, parent_logical_name=None)

    def _build_tables_from_element(
        self, element: ET.Element, context: dict[str, Any], parent_logical_name: str | None
    ) -> list[ParsedTable]:
        logical_name = _sanitize(element.tag)
        row: dict[str, Any] = dict(context)

        for key, value in element.attrib.items():
            safe_key = _sanitize(key)
            if safe_key not in row:
                row[safe_key] = _coerce_scalar(value)

        child_tables: list[ParsedTable] = []
        children_by_tag: dict[str, list[ET.Element]] = {}

        for child in list(element):
            tag = _sanitize(child.tag)
            children_by_tag.setdefault(tag, []).append(child)

        for tag, children in children_by_tag.items():
            if len(children) == 1 and not list(children[0]):
                text = (children[0].text or "").strip()
                if text:
                    flat_key = tag
                    counter = 1
                    while flat_key in row:
                        flat_key = f"{tag}_{counter}"
                        counter += 1
                    row[flat_key] = _coerce_scalar(text)
                continue

            if len(children) >= 1 and any(list(child) for child in children):
                child_rows: list[dict[str, Any]] = []
                for child in children:
                    child_row = dict(context)
                    for key, value in child.attrib.items():
                        safe_key = _sanitize(key)
                        if safe_key not in child_row:
                            child_row[safe_key] = _coerce_scalar(value)
                    for grandchild in list(child):
                        gtag = _sanitize(grandchild.tag)
                        gtext = (grandchild.text or "").strip()
                        if gtext and not list(grandchild):
                            flat_key = gtag
                            counter = 1
                            while flat_key in child_row:
                                flat_key = f"{gtag}_{counter}"
                                counter += 1
                            child_row[flat_key] = _coerce_scalar(gtext)
                    child_rows.append(child_row)

                if child_rows:
                    child_tables.append(
                        ParsedTable(
                            logical_name=tag,
                            rows=child_rows,
                            required_columns=["document_id"],
                            include_traceability_columns=False,
                            relationships=[
                                TableRelationship(
                                    parent_logical_name=parent_logical_name or logical_name,
                                    parent_key="document_id",
                                    child_key="document_id",
                                )
                            ],
                        )
                    )

            for child in children:
                if len(children) == 1:
                    child_tables.extend(self._build_tables_from_element(child, context, parent_logical_name=tag))

        root_table = ParsedTable(
            logical_name=logical_name,
            rows=[row],
            required_columns=["document_id"],
            include_traceability_columns=False,
        )

        return [root_table] + child_tables

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        # XML output is generated via structured table projection in _parse_file.
        return [], []


class SyslogPipeline(DeterministicParserPipeline):
    parser_key = "syslog"
    supported_extensions = (".syslog", ".log")

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:25] if line.strip()]
        if not lines:
            return 0.0
        hits = sum(1 for line in lines if SYSLOG_RE.match(line))
        return hits / len(lines)

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            match = SYSLOG_RE.match(stripped)
            if match is None:
                warnings.append(f"line {index}: not valid syslog format")
                continue

            message = match.group("message") or ""

            row: dict[str, Any] = {
                "timestamp": match.group("timestamp"),
                "host": match.group("host"),
                "process": match.group("process"),
                "pid": _cast_value(match.group("pid") or ""),
                "message": message[:500],
                "log_level": _infer_log_level(message or stripped),
                "source": filename,
                "raw": stripped[:4000],
            }

            # Parse embedded logfmt payload (e.g. "tool=ETCH-01 chamber=A ...")
            if message and ("=" in message):
                pairs = LOGFMT_RE.findall(message)
                if pairs and len(pairs) >= 1:
                    for key, value in pairs:
                        safe_key = _sanitize(key)
                        if safe_key not in row:
                            row[safe_key] = _cast_value(value.strip().strip('"'))

            pri = match.group("pri")
            if pri is not None:
                pri_value = int(pri)
                row["syslog_pri"] = pri_value
                row["syslog_facility"] = pri_value // 8
                row["syslog_severity"] = pri_value % 8
            rows.append(row)
        return rows, warnings


class ApacheAccessPipeline(DeterministicParserPipeline):
    parser_key = "apache_access"

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:25] if line.strip()]
        if not lines:
            return 0.0
        hits = sum(1 for line in lines if APACHE_ACCESS_RE.match(line))
        return hits / len(lines)

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        return _parse_access_rows(content, filename)


class NginxAccessPipeline(DeterministicParserPipeline):
    parser_key = "nginx_access"

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:25] if line.strip()]
        if not lines:
            return 0.0
        hits = 0
        for line in lines:
            if APACHE_ACCESS_RE.match(line) and ("nginx" in line.lower() or "upstream" in line.lower()):
                hits += 1
        if hits == 0:
            hits = sum(1 for line in lines if APACHE_ACCESS_RE.match(line))
        return hits / len(lines)

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        return _parse_access_rows(content, filename)


class LogfmtPipeline(DeterministicParserPipeline):
    parser_key = "logfmt"

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:25] if line.strip()]
        if not lines:
            return 0.0
        hits = sum(1 for line in lines if len(LOGFMT_RE.findall(line)) >= 2)
        return hits / len(lines)

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            pairs = LOGFMT_RE.findall(stripped)
            if len(pairs) < 1:
                warnings.append(f"line {index}: no logfmt pairs")
                continue

            row: dict[str, Any] = {
                "source": filename,
                "raw": stripped[:4000],
                "message": stripped[:500],
                "log_level": _infer_log_level(stripped),
            }
            for key, value in pairs:
                row[_sanitize(key)] = _cast_value(value.strip().strip('"'))
            rows.append(row)
        return rows, warnings


class KeyValuePipeline(DeterministicParserPipeline):
    parser_key = "key_value"

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:25] if line.strip()]
        if not lines:
            return 0.0
        hits = sum(1 for line in lines if len(KEY_VALUE_RE.findall(line)) >= 2)
        return hits / len(lines)

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            pairs = KEY_VALUE_RE.findall(stripped)
            if len(pairs) < 1:
                warnings.append(f"line {index}: no key-value pairs")
                continue

            row: dict[str, Any] = {
                "source": filename,
                "raw": stripped[:4000],
                "message": stripped[:500],
                "log_level": _infer_log_level(stripped),
            }
            for key, value in pairs:
                row[_sanitize(key)] = _cast_value(value.strip().strip('"'))
            rows.append(row)
        return rows, warnings


HEX_PAIR_RE = re.compile(r"\b[0-9a-fA-F]{2}\b")
HEX_DUMP_LINE_RE = re.compile(r"^\s*[0-9a-fA-F]{4,8}[\s:]*((?:\s+[0-9a-fA-F]{2})+)(?:\s+\|[^|]*\|)?$")
PRINTABLE_STRING_RE = re.compile(r"[\x20-\x7e]{4,}")
TIMESTAMP_IN_HEX_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


class BinaryHexPipeline(DeterministicParserPipeline):
    parser_key = "binary_hex"
    supported_extensions = (".bin", ".hex", ".dump")
    structured_output = True

    def supports(self, request: ParserSupportRequest) -> ParserSupportResult:
        lower_name = request.filename.lower()
        extension_match = self.supported_extensions and any(
            lower_name.endswith(ext) for ext in self.supported_extensions
        )
        content_score = self._score_content(request.content)

        if extension_match and content_score > 0.0:
            return ParserSupportResult(
                parser_key=self.parser_key,
                supported=True,
                score=min(1.0, content_score),
                reasons=["File extension and content strongly match binary/hex parser."],
            )

        if extension_match:
            return ParserSupportResult(
                parser_key=self.parser_key,
                supported=True,
                score=0.95,
                reasons=["File extension strongly matches parser."],
            )

        return ParserSupportResult(
            parser_key=self.parser_key,
            supported=content_score >= 0.6,
            score=round(content_score, 2),
            reasons=["Binary/hex content scoring."],
        )

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:25] if line.strip()]
        if not lines:
            return 0.0

        hex_dump_lines = sum(1 for line in lines if HEX_DUMP_LINE_RE.match(line))
        if hex_dump_lines >= 3:
            return 1.0

        if chardet is not None:
            result = chardet.detect(content.encode("utf-8", errors="replace"))
            if result and result.get("encoding") in ("binary", None) and result.get("confidence", 0) > 0.7:
                return 0.95

        total_pairs = sum(len(HEX_PAIR_RE.findall(line)) for line in lines)
        avg_pairs = total_pairs / max(len(lines), 1)
        if avg_pairs >= 8:
            return 0.85

        printable = PRINTABLE_STRING_RE.findall(content)
        if len(printable) >= 5:
            return 0.6

        return 0.0

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []

        lines = content.splitlines()
        hex_dump_lines = [line for line in lines if HEX_DUMP_LINE_RE.match(line)]

        if hex_dump_lines:
            offset = 0
            for line in lines:
                match = HEX_DUMP_LINE_RE.match(line)
                if not match:
                    continue
                hex_part = match.group(1)
                hex_bytes = hex_part.replace(" ", "")
                if len(hex_bytes) % 2 != 0:
                    continue
                try:
                    raw = binascii.unhexlify(hex_bytes)
                except (binascii.Error, ValueError):
                    continue

                ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
                decoded_text = ""
                try:
                    decoded_text = raw.decode("utf-8", errors="ignore")
                except UnicodeDecodeError:
                    pass

                timestamp = None
                for ts_match in TIMESTAMP_IN_HEX_RE.finditer(ascii_repr):
                    timestamp = ts_match.group(0)
                    break

                rows.append(
                    {
                        "offset": offset,
                        "hex_bytes": hex_bytes,
                        "ascii_repr": ascii_repr,
                        "decoded_text": decoded_text or None,
                        "timestamp": timestamp,
                        "source_file": filename,
                    }
                )
                offset += len(raw)

            return rows, warnings

        printable_strings = PRINTABLE_STRING_RE.findall(content)
        if printable_strings:
            for string_index, text in enumerate(printable_strings[:500], start=1):
                timestamp = None
                for ts_match in TIMESTAMP_IN_HEX_RE.finditer(text):
                    timestamp = ts_match.group(0)
                    break

                rows.append(
                    {
                        "string_index": string_index,
                        "text": text,
                        "timestamp": timestamp,
                        "source_file": filename,
                    }
                )
            return rows, warnings

        warnings.append("No recognizable hex dump or printable strings found.")
        return rows, warnings


# ── SectionedKeyValuePipeline ───────────────────────────────────────────────
# Handles blank-line-delimited blocks of "Key: Value" lines
# (e.g. windows_event.log, keyvalue_pairs.log)


SECTION_HEADER_RE = re.compile(r"^\[.*\]\s*$")
COLON_KV_RE = re.compile(r"^([A-Za-z][\w\s]*)\s*:\s*(.+)$")


class SectionedKeyValuePipeline(DeterministicParserPipeline):
    """Parser for blank-line-separated KEY: VALUE blocks (Windows Event Log style)."""

    parser_key = "sectioned_kv"
    structured_output = True

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:30] if line.strip()]
        if not lines:
            return 0.0

        # Count blank-line-separated blocks with colon KV lines
        colon_kv_lines = sum(1 for line in lines if COLON_KV_RE.match(line))
        if colon_kv_lines < 2:
            return 0.0

        # Count section boundaries (blank lines in full content)
        all_lines = content.splitlines()
        if len(all_lines) < 5:
            return 0.0
        blank_count = 0
        for line in all_lines[:50]:
            if not line.strip():
                blank_count += 1

        if blank_count < 2 and colon_kv_lines < 4:
            return 0.0

        return min(0.95, colon_kv_lines / max(len(lines), 1))

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        blocks = self._split_blocks(content)

        for block_index, block in enumerate(blocks, start=1):
            block_lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not block_lines:
                continue

            row: dict[str, Any] = {
                "source_file": filename,
                "block_index": block_index,
                "raw": block.strip()[:4000],
            }

            # Check for a header line like [timestamp] or section header
            header_line = block_lines[0]
            if SECTION_HEADER_RE.match(header_line):
                row["header"] = header_line
                block_lines = block_lines[1:]
            elif COLON_KV_RE.match(header_line):
                pass  # first line is a KV pair, no separate header
            else:
                row["header"] = header_line
                block_lines = block_lines[1:]

            # Parse KEY: VALUE pairs
            for line in block_lines:
                match = COLON_KV_RE.match(line)
                if not match:
                    continue
                key = _sanitize(match.group(1).strip())
                value = _cast_value(match.group(2).strip())
                if key == "event_id":
                    key = "event_id"
                row[key] = value

            # Build message from key fields
            message_parts = []
            for msg_field in ("message", "Message", "MESSAGE", "event_id", "Event ID", "EVENT_TYPE"):
                val = row.get(_sanitize(msg_field))
                if val is not None:
                    message_parts.append(str(val))
            row["message"] = " | ".join(message_parts) if message_parts else block_lines[0][:500]

            # Infer log level
            raw_text = " ".join(block_lines)
            row["log_level"] = _infer_log_level(raw_text)

            # Set source file
            row["source"] = filename

            rows.append(row)

        if not rows:
            warnings.append("No sectioned key-value blocks found.")
        return rows, warnings

    @staticmethod
    def _split_blocks(content: str) -> list[str]:
        """Split content into blank-line-separated blocks."""
        blocks: list[str] = []
        current: list[str] = []
        for line in content.splitlines():
            if line.strip():
                current.append(line)
            else:
                if current:
                    blocks.append("\n".join(current))
                    current = []
        if current:
            blocks.append("\n".join(current))
        return blocks


# ── TimestampedEventTextPipeline ────────────────────────────────────────────
# Handles plaintext events with bracketed or ISO timestamps, continuation lines
# (e.g. alarm_events.log, plaintext_events.log, multiline_java.log)


TIMESTAMPED_LINE_RE = re.compile(
    r"^(?:"
    r"\[\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}:\d{2}"  # [2026-04-17 08:03:15...
    r"|\d{2}[-/]\d{2}[-/]\d{4}\s+\d{2}:\d{2}:\d{2}\.\d+"  # 03/06/2026 12:00:00.000
    r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"  # 2024-01-15 10:30:00
    r")",
)
EVENT_CODE_RE = re.compile(r"\b[A-Z]{2,4}-\d+[A-Z0-9]*\b")


class TimestampedEventTextPipeline(DeterministicParserPipeline):
    """Parser for timestamped plaintext event logs with optional continuation lines."""

    parser_key = "timestamped_event"
    structured_output = True

    def _score_content(self, content: str) -> float:
        lines = [line for line in content.splitlines()[:30] if line.strip()]
        if not lines:
            return 0.0

        ts_hits = sum(1 for line in lines if TIMESTAMPED_LINE_RE.match(line))
        if ts_hits == 0:
            # Try multiline continuation detection for Java stack traces
            continuation_hits = sum(1 for line in lines if MULTILINE_CONTINUATION_PATTERN.match(line))
            if continuation_hits > 0 and ts_hits > 0:
                return 0.7
            if continuation_hits >= 3:
                # Could be a stack trace file; check for timestamped lines too
                iso_hits = sum(1 for line in lines if ISO_TIMESTAMP_RE.match(line))
                if iso_hits > 0:
                    return 0.7
            return 0.0

        ts_ratio = ts_hits / len(lines)
        if ts_ratio >= 0.5:
            return min(0.9, ts_ratio + 0.2)
        if ts_ratio >= 0.2:
            return ts_ratio + 0.1
        return 0.0

    def _parse_rows(self, content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
        rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        lines = content.splitlines()

        events = self._cluster_events(lines, filename)
        for event_index, event_lines in enumerate(events, start=1):
            if not event_lines:
                continue

            row = self._parse_event(event_lines, filename, event_index)
            rows.append(row)

        if not rows:
            warnings.append("No timestamped events found.")
        return rows, warnings

    @staticmethod
    def _cluster_events(lines: list[str], filename: str) -> list[list[str]]:
        """Group continuation lines into their parent event blocks."""
        events: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            stripped = line.rstrip("\n")
            if TIMESTAMPED_LINE_RE.match(stripped) or ISO_TIMESTAMP_RE.match(stripped):
                if current:
                    events.append(current)
                current = [stripped]
            elif current and MULTILINE_CONTINUATION_PATTERN.match(stripped):
                current.append(stripped)
            elif current:
                # Non-timestamped, non-continuation: add to current if it looks related
                if not stripped.strip():
                    if current:
                        events.append(current)
                        current = []
                else:
                    current.append(stripped)
            elif stripped.strip() and not current:
                current = [stripped]

        if current:
            events.append(current)
        return events

    def _parse_event(self, event_lines: list[str], filename: str, event_index: int) -> dict[str, Any]:
        head_line = event_lines[0]
        row: dict[str, Any] = {
            "source_file": filename,
            "event_index": event_index,
        }

        # Extract timestamp
        ts_match = TIMESTAMPED_LINE_RE.match(head_line)
        if not ts_match:
            ts_match = ISO_TIMESTAMP_RE.match(head_line)
        if ts_match:
            row["timestamp"] = ts_match.group(0)

        # Infer log level
        combined_text = " ".join(event_lines)
        row["log_level"] = _infer_log_level(combined_text)

        # Extract event codes like E2331, DW-20E2, ER-4102
        event_codes = EVENT_CODE_RE.findall(combined_text)
        if event_codes:
            row["event_code"] = event_codes[0]

        # Build message
        if len(event_lines) == 1:
            row["message"] = head_line[:500]
        else:
            # First line is the event header, continuation lines are the body/detail
            row["header"] = head_line[:500]
            body_lines = []
            for line in event_lines[1:]:
                body_lines.append(line.strip())
            row["message"] = " ".join(body_lines)[:500]

        row["raw"] = "\n".join(event_lines)[:4000]
        row["source"] = filename
        return row


def _parse_access_rows(content: str, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = APACHE_ACCESS_RE.match(stripped)
        if match is None:
            warnings.append(f"line {index}: not valid access log format")
            continue

        row: dict[str, Any] = {
            "ip": match.group("ip"),
            "ident": match.group("ident"),
            "authuser": match.group("authuser"),
            "timestamp": match.group("timestamp"),
            "request": match.group("request"),
            "status": _cast_value(match.group("status")),
            "body_bytes": _cast_value(match.group("body_bytes")),
            "referer": match.group("referer"),
            "user_agent": match.group("user_agent"),
            "source": filename,
            "raw": stripped[:4000],
            "message": stripped[:500],
            "log_level": _status_to_level(_cast_value(match.group("status"))),
        }
        rows.append(row)
    return rows, warnings


def _infer_sql_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, dict):
        return "JSON"
    return "TEXT"


def _merge_sql_types(type_set: set[str]) -> str:
    if not type_set:
        return "TEXT"
    if "TEXT" in type_set:
        return "TEXT"
    if "JSON" in type_set:
        return "JSON"
    if "REAL" in type_set:
        return "REAL"
    if "INTEGER" in type_set and "BOOLEAN" in type_set:
        return "INTEGER"
    if "INTEGER" in type_set:
        return "INTEGER"
    if "BOOLEAN" in type_set:
        return "BOOLEAN"
    return "TEXT"


def _flatten_json(value: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    if depth > 4:
        return {prefix.rstrip("_") or "value": json.dumps(value, ensure_ascii=True)}

    result: dict[str, Any] = {}
    for key, raw in value.items():
        safe_key = _sanitize(key)
        full_key = f"{prefix}{safe_key}" if prefix else safe_key
        if isinstance(raw, dict):
            result.update(_flatten_json(raw, prefix=f"{full_key}_", depth=depth + 1))
        elif isinstance(raw, list):
            if len(raw) <= 10 and all(not isinstance(item, (dict, list)) for item in raw):
                result[full_key] = ",".join(str(item) for item in raw)
            else:
                result[full_key] = json.dumps(raw, ensure_ascii=True)
        else:
            result[full_key] = raw
    return result


def _flatten_json_scalars(value: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    used_names: set[str] = set()

    def _flatten(current: dict[str, Any], current_prefix: str = "", current_depth: int = 0) -> dict[str, Any]:
        if current_depth > 4:
            key = unique_identifier(current_prefix.rstrip("_") or "value", used_names)
            used_names.add(key)
            return {key: json.dumps(current, ensure_ascii=True)}

        result: dict[str, Any] = {}
        for key, raw in current.items():
            safe_key = _sanitize(key)
            full_key = f"{current_prefix}{safe_key}" if current_prefix else safe_key
            if isinstance(raw, dict):
                result.update(_flatten(raw, current_prefix=f"{full_key}_", current_depth=current_depth + 1))
            elif isinstance(raw, list):
                unique_key = unique_identifier(full_key, used_names)
                used_names.add(unique_key)
                if all(_is_scalar(item) for item in raw):
                    result[unique_key] = ",".join(str(_coerce_scalar(item)) for item in raw)
                else:
                    result[unique_key] = json.dumps(raw, ensure_ascii=True)
            else:
                unique_key = unique_identifier(full_key, used_names)
                used_names.add(unique_key)
                result[unique_key] = _coerce_scalar(raw)
        return result

    return _flatten(value, prefix, depth)


def _sanitize(value: str) -> str:
    return sanitize_identifier(value)


def _cast_value(value: str | None) -> Any:
    return coerce_scalar(value)


def _status_to_level(status: Any) -> str:
    if isinstance(status, int):
        if status >= 500:
            return "ERROR"
        if status >= 400:
            return "WARNING"
    return "INFO"


def _infer_log_level(raw: str) -> str:
    lowered = raw.lower()
    if "critical" in lowered or "panic" in lowered:
        return "CRITICAL"
    if "fatal" in lowered:
        return "FATAL"
    if "error" in lowered:
        return "ERROR"
    if "warn" in lowered:
        return "WARNING"
    if "debug" in lowered:
        return "DEBUG"
    if "trace" in lowered:
        return "TRACE"
    return "INFO"


def _coerce_scalar(value: Any, preserve_empty: bool = True) -> Any:
    return coerce_scalar(value, preserve_empty=preserve_empty)


def _normalize_iso_timestamp(value: str) -> str | None:
    candidate = value.strip().replace(" ", "T")
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _stable_hash(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _logical_name_from_filename(filename: str) -> str:
    return _sanitize(Path(filename).stem or "records")


def _sniff_delimiter(lines: list[str]) -> str | None:
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        return dialect.delimiter
    except csv.Error:
        pass

    best_delimiter: str | None = None
    best_score = 0.0
    for delimiter in [",", "\t", "|", ";"]:
        counts = [line.count(delimiter) for line in lines[:10]]
        active = [count for count in counts if count > 0]
        if len(active) < 2:
            continue
        if max(active) == 0:
            continue
        consistency = sum(1 for count in active if count == active[0]) / len(active)
        score = consistency * (active[0] + 1)
        if score > best_score:
            best_score = score
            best_delimiter = delimiter

    return best_delimiter


def _detect_header(lines: list[str], delimiter: str) -> bool:
    if len(lines) < 2:
        return False

    sample = "\n".join(lines[:20])
    try:
        if csv.Sniffer().has_header(sample):
            return True
    except csv.Error:
        pass

    first_row = next(csv.reader([lines[0]], delimiter=delimiter))
    second_row = next(csv.reader([lines[1]], delimiter=delimiter))
    if len(first_row) != len(second_row):
        return False

    token_score = 0
    for token in first_row:
        cleaned = token.strip()
        if cleaned and not NUMBER_RE.match(cleaned):
            token_score += 1

    return token_score / max(len(first_row), 1) >= 0.6


def _parse_delimited_rows(
    lines: list[str],
    delimiter: str,
    has_header: bool,
    filename: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    reader = csv.reader(lines, delimiter=delimiter)
    all_rows = list(reader)
    if not all_rows:
        return [], []

    if has_header:
        header = [_sanitize(cell) or f"column_{index + 1}" for index, cell in enumerate(all_rows[0])]
        data_rows = all_rows[1:]
    else:
        width = max(len(row) for row in all_rows)
        header = [f"column_{index + 1}" for index in range(width)]
        data_rows = all_rows

    deduped_header: list[str] = []
    seen: dict[str, int] = {}
    for name in header:
        count = seen.get(name, 0)
        seen[name] = count + 1
        deduped_header.append(name if count == 0 else f"{name}_{count + 1}")

    result_rows: list[dict[str, Any]] = []
    for row in data_rows:
        normalized = [cell.strip() for cell in row]
        if len(normalized) < len(deduped_header):
            normalized.extend([""] * (len(deduped_header) - len(normalized)))

        mapped: dict[str, Any] = {"source_file": filename}
        for index, column_name in enumerate(deduped_header):
            value = normalized[index] if index < len(normalized) else ""
            mapped[column_name] = _coerce_scalar(value, preserve_empty=True)
        result_rows.append(mapped)

    return result_rows, deduped_header


def _tabular_quality_score(rows: list[dict[str, Any]], columns: list[str]) -> float:
    if not rows or not columns:
        return 0.0

    non_null = 0
    total = 0
    for row in rows:
        for column in columns:
            total += 1
            if row.get(column) is not None:
                non_null += 1

    header_penalty = 1.0
    if rows and _detect_header_row_as_data_candidate(rows[0], columns):
        header_penalty = 0.1

    return (non_null / max(total, 1)) * header_penalty


def _detect_header_row_as_data_candidate(first_row: dict[str, Any], columns: list[str]) -> bool:
    comparable = [column for column in columns if column in first_row]
    if not comparable:
        return False
    matches = 0
    for column in comparable:
        value = first_row.get(column)
        if isinstance(value, str) and value.lower() == column.lower():
            matches += 1
    return matches / len(comparable) >= 0.7


def _compute_null_ratios_for_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {}
    ratios: dict[str, float] = {}
    all_columns: set[str] = set()
    for row in rows:
        all_columns.update(row.keys())
    for column in all_columns:
        null_count = 0
        for row in rows:
            if row.get(column) is None:
                null_count += 1
        ratios[column] = round(null_count / len(rows), 3)
    return ratios
