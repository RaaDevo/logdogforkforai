from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from parsers.contracts import ClassificationResult, FileClassification, StructuralClass  # noqa: E402
from parsers.preprocessor import FileInput  # noqa: E402
from parsers.unified.pipeline import UnifiedPipeline  # noqa: E402


def _classification(filename: str, detected_format: str) -> ClassificationResult:
    return ClassificationResult(
        dominant_format=detected_format,
        structural_class=StructuralClass.SEMI_STRUCTURED,
        selected_parser_key="unified",
        file_classifications=[
            FileClassification(
                file_id="f1",
                filename=filename,
                detected_format=detected_format,
                structural_class=StructuralClass.SEMI_STRUCTURED,
                format_confidence=0.95,
                line_count=6,
            )
        ],
    )


def test_unified_compacts_sparse_json_fields_into_extra() -> None:
    pipeline = UnifiedPipeline()
    file_input = FileInput(
        file_id="f1",
        filename="events.json",
        content="\n".join(
            [
                '{"timestamp":"2026-01-01T00:00:00Z","message":"a","user":"u1","service":"auth"}',
                '{"timestamp":"2026-01-01T00:00:01Z","message":"b","user":"u2","service":"auth"}',
                '{"timestamp":"2026-01-01T00:00:02Z","message":"c","user":"u3","service":"auth"}',
                '{"timestamp":"2026-01-01T00:00:03Z","message":"d","user":"u4","service":"auth","rare_token":"x"}',
                '{"timestamp":"2026-01-01T00:00:04Z","message":"e","user":"u5","service":"auth"}',
                '{"timestamp":"2026-01-01T00:00:05Z","message":"f","user":"u6","service":"auth","error_code":"E42"}',
            ]
        ),
    )

    result = pipeline.parse([file_input], _classification(file_input.filename, "json_lines"))

    assert result.table_definitions
    table = result.table_definitions[0]
    names = {column.name for column in table.columns}
    assert "rare_token" not in names
    assert "error_code" in names

    rows = result.records[table.table_name]
    row_with_rare = next(row for row in rows if '"rare_token":"x"' in row.get("extra", ""))
    assert "rare_token" not in row_with_rare
    assert '"rare_token":"x"' in row_with_rare["extra"]

    diagnostics = result.diagnostics["files"][file_input.filename]
    assert "rare_token" in diagnostics["dropped_sparse_columns"]
    assert diagnostics["column_coverage"]["rare_token"] < diagnostics["sparse_column_threshold"]


def test_unified_compacts_sparse_csv_fields_into_extra() -> None:
    pipeline = UnifiedPipeline()
    file_input = FileInput(
        file_id="f1",
        filename="mixed.log",
        content="\n".join(
            [
                "timestamp,message,host,error_code,rare_tag",
                "2026-01-01T00:00:00Z,start,api-1,,",
                "2026-01-01T00:00:01Z,ok,api-1,,",
                "2026-01-01T00:00:02Z,ok,api-2,,",
                "2026-01-01T00:00:03Z,fail,api-3,E9,only-once",
                "2026-01-01T00:00:04Z,ok,api-4,,",
            ]
        ),
    )

    result = pipeline.parse([file_input], _classification(file_input.filename, "csv"))
    table = result.table_definitions[0]
    names = {column.name for column in table.columns}
    assert "rare_tag" not in names
    assert "error_code" in names

    rows = result.records[table.table_name]
    sparse_in_extra = [row for row in rows if '"rare_tag":"only-once"' in row.get("extra", "")]
    assert sparse_in_extra
