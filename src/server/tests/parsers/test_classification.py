from __future__ import annotations

from pathlib import Path

import pytest

from parsers.preprocessor import FileInput, LogPreprocessorService
from parsers.registry import ParserRegistry
from parsers.schema_cache import SchemaCache

SAMPLES_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "samples"


def _make_service() -> LogPreprocessorService:
    """Create a preprocessor without DB-backed cache for testing."""
    return LogPreprocessorService(
        use_llm=False,
        schema_cache=SchemaCache(use_persistence=False),
    )


def _iter_samples() -> list[Path]:
    """Return sample file paths (excluding .gold.json comparison files)."""
    return sorted(p for p in SAMPLES_ROOT.iterdir() if not p.name.endswith(".gold.json"))


# ── Parametrized classification tests ──────────────────────────────────────


@pytest.mark.parametrize(
    "filename,expected_parser_key",
    [
        # Structured formats
        ("json_nested.json", "json_lines"),
        ("deposition_run.json", "json_lines"),
        ("vendor1_trace.json", "json_lines"),
        ("vendor2_alarms.json", "json_lines"),
        ("vendor3_constants.json", "json_lines"),
        ("lot_wafer_history.ndjson", "json_lines"),
        ("parquet_metadata.json", "json_lines"),
        ("json_process_setpoints.json", "json_lines"),
        ("recipe_definition.xml", "xml"),
        # CSV/TSV
        ("csv_sensors.csv", "csv"),
        ("etch_sensor_trace.csv", "csv"),
        ("metrology_results.tsv", "csv"),
        # Syslog
        ("syslog_events.log", "syslog"),
        ("tool_syslog.log", "syslog"),
        # Logfmt / key-value
        ("kv_status_trace.txt", "logfmt"),
        # Binary / hex
        ("binary_hex.hex", "binary_hex"),
        ("controller_dump.hex", "binary_hex"),
        ("plc_snapshot.bin", "binary_hex"),
        # Sectioned key-value blocks
        ("windows_event.log", "sectioned_kv"),
        ("keyvalue_pairs.log", "sectioned_kv"),
        # Timestamped event text
        ("alarm_events.log", "timestamped_event"),
        ("plaintext_events.log", "sectioned_kv"),
        ("multiline_java.log", "timestamped_event"),
        # XML recipe (was misclassified)
        ("xml_recipe.xml", "xml"),
        # XML log
        ("xml.log", "xml"),
    ],
)
def test_parser_selection(filename: str, expected_parser_key: str) -> None:
    """Verify each sample file routes to the expected parser."""
    sample_file = SAMPLES_ROOT / filename
    assert sample_file.exists(), f"Sample file not found: {sample_file}"

    content = sample_file.read_text(errors="replace")
    file_input = FileInput(filename=filename, content=content)

    svc = _make_service()
    classification = svc.classify([file_input])

    fc = classification.file_classifications[0]
    assert (
        classification.selected_parser_key == expected_parser_key
    ), (
        f"{filename}: expected parser '{expected_parser_key}' "
        f"but got '{classification.selected_parser_key}' "
        f"(format={fc.detected_format}, confidence={fc.format_confidence})"
    )


# ── Non-empty extraction tests ─────────────────────────────────────────────


@pytest.mark.parametrize("sample_name", _iter_samples())
def test_all_samples_produce_records(sample_name: Path) -> None:
    """Every sample file should produce at least one record."""
    sample_file = sample_name
    content = sample_file.read_text(errors="replace")
    file_input = FileInput(filename=sample_file.name, content=content)

    svc = _make_service()
    classification = svc.classify([file_input])
    parser_key = classification.selected_parser_key

    pipeline = ParserRegistry.route(parser_key)
    result = pipeline.ingest([file_input], classification)

    total_rows = sum(len(rows) for rows in result.records.values())
    assert total_rows > 0, (
        f"{sample_file.name}: parser '{parser_key}' produced 0 records "
        f"(confidence={result.confidence})"
    )


# ── Confidence threshold tests ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename,min_confidence",
    [
        ("recipe_definition.xml", 0.8),
        ("csv_sensors.csv", 0.8),
        ("kv_status_trace.txt", 0.8),
        ("json_nested.json", 0.8),
        ("deposition_run.json", 0.8),
        ("syslog_events.log", 0.8),
        ("tool_syslog.log", 0.8),
        ("binary_hex.hex", 0.6),
        ("controller_dump.hex", 0.6),
        ("windows_event.log", 0.4),
        ("keyvalue_pairs.log", 0.4),
        ("alarm_events.log", 0.4),
        ("plaintext_events.log", 0.4),
        ("multiline_java.log", 0.4),
    ],
)
def test_min_format_confidence(filename: str, min_confidence: float) -> None:
    """Well-structured logs should have format confidence above threshold."""
    sample_file = SAMPLES_ROOT / filename
    content = sample_file.read_text(errors="replace")
    file_input = FileInput(filename=filename, content=content)

    svc = _make_service()
    classification = svc.classify([file_input])

    fc = classification.file_classifications[0]
    assert fc.format_confidence >= min_confidence, (
        f"{filename}: format confidence {fc.format_confidence} < {min_confidence}"
    )


# ── Parser-specific extraction quality tests ────────────────────────────────


def test_tool_syslog_extracts_payload_fields() -> None:
    """Syslog with structured payloads should extract tool/chamber/event fields."""
    sample_file = SAMPLES_ROOT / "tool_syslog.log"
    content = sample_file.read_text(errors="replace")
    file_input = FileInput(filename="tool_syslog.log", content=content)

    svc = _make_service()
    classification = svc.classify([file_input])
    pipeline = ParserRegistry.route(classification.selected_parser_key)
    result = pipeline.ingest([file_input], classification)

    all_rows = list(result.records.values())
    assert all_rows, "No records produced for tool_syslog.log"
    first_row = all_rows[0][0] if isinstance(all_rows[0], list) else all_rows[0]

    # Should have extracted structured fields from the logfmt payload
    for field in ("tool", "chamber", "event"):
        assert field in first_row or f"_{field}" in first_row, (
            f"Expected field '{field}' in parsed row keys: {list(first_row.keys())}"
        )


def test_windows_event_produces_event_records() -> None:
    """Windows event log should produce one row per event block."""
    sample_file = SAMPLES_ROOT / "windows_event.log"
    content = sample_file.read_text(errors="replace")
    file_input = FileInput(filename="windows_event.log", content=content)

    svc = _make_service()
    classification = svc.classify([file_input])
    pipeline = ParserRegistry.route(classification.selected_parser_key)
    result = pipeline.ingest([file_input], classification)

    all_rows = list(result.records.values())
    assert all_rows, "No records produced"

    rows = all_rows[0] if isinstance(all_rows[0], list) else []
    # 3 events in windows_event.log
    assert len(rows) == 3, f"Expected 3 event rows, got {len(rows)}"
    first = rows[0]
    assert any("event" in str(k).lower() for k in first.keys()) or any(
        "id" in str(k).lower() for k in first.keys()
    ), f"No event/id field in {list(first.keys())}"
