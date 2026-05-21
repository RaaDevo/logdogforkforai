from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from parsers.contracts import (  # noqa: E402
    ClassificationResult,
    FileClassification,
    ParserPipelineResult,
    StructuralClass,
)
from parsers.orchestrator import _record_feedback  # noqa: E402
from parsers.preprocessor import FileInput  # noqa: E402


def test_record_feedback_success_uses_table_definitions_not_removed_errors(monkeypatch) -> None:
    update_feedback_calls: list[dict[str, object]] = []
    profile_route_calls: list[dict[str, object]] = []
    schema_route_calls: list[dict[str, object]] = []

    class FakeProfileStore:
        def update_feedback(self, **kwargs):
            update_feedback_calls.append(kwargs)

        def record_route_outcome(self, **kwargs):
            profile_route_calls.append(kwargs)

    class FakeSchemaCache:
        def get_by_fingerprint(self, **kwargs):
            return SimpleNamespace(schema_key="schema-1")

        def record_route_outcome(self, schema_key, **kwargs):
            schema_route_calls.append({"schema_key": schema_key, **kwargs})

    monkeypatch.setattr("parsers.parser_profiles.ParserProfileStore", FakeProfileStore)
    monkeypatch.setattr("parsers.schema_cache.SchemaCache", FakeSchemaCache)
    monkeypatch.setattr("parsers.orchestrator.get_profile", lambda _profile_name: SimpleNamespace(domain="ops"))

    file_inputs = [
        FileInput(file_id="f1", filename="app.log", content="line1\nline2\n"),
    ]
    classification = ClassificationResult(
        dominant_format="syslog",
        structural_class=StructuralClass.SEMI_STRUCTURED,
        selected_parser_key="syslog",
        file_classifications=[
            FileClassification(
                file_id="f1",
                filename="app.log",
                detected_format="syslog",
                structural_class=StructuralClass.SEMI_STRUCTURED,
                format_confidence=0.9,
                line_count=2,
            )
        ],
    )
    result = ParserPipelineResult(
        table_definitions=[],
        records={},
        parser_key="syslog",
        warnings=["minor warning"],
    )

    _record_feedback(file_inputs=file_inputs, classification=classification, result=result, profile_name="default")

    assert update_feedback_calls and update_feedback_calls[0]["success"] is False
    assert profile_route_calls and profile_route_calls[0]["success"] is False
    assert schema_route_calls and schema_route_calls[0]["success"] is False
