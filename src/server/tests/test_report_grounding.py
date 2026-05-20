from __future__ import annotations

import json
from pathlib import Path
import re


SERVER_ROOT = Path(__file__).resolve().parents[1]
ROUTES_FILE = SERVER_ROOT / "src/routes/logs.py"


def _load_validate_report_grounding():
    src = ROUTES_FILE.read_text(encoding="utf-8")
    match = re.search(
        r"def _validate_report_grounding\(report: LogInsightReport, context: str\) -> list\[str\]:\n(?P<body>(?:    .*\n)+?)\n\ndef _fetch_group_rows_for_report",
        src,
    )
    assert match, "Could not locate _validate_report_grounding in routes/logs.py"
    fn_src = "def _validate_report_grounding(report, context):\n" + match.group("body")
    namespace: dict[str, object] = {"re": re}
    exec(fn_src, namespace)  # noqa: S102
    return namespace["_validate_report_grounding"]


class StubReport:
    def __init__(self, *, top_errors: list[str], anomalies: list[str], root_cause_hypothesis: str):
        self.top_errors = top_errors
        self.anomalies = anomalies
        self.root_cause_hypothesis = root_cause_hypothesis


def test_grounding_flags_unsupported_claims_and_reduces_score() -> None:
    validate = _load_validate_report_grounding()
    context = "error e_timeout seen in row 1; anomaly packet loss seen in row 2"
    report = StubReport(
        top_errors=["error e_timeout seen in row 1", "error e_oom not present in data"],
        anomalies=["anomaly packet loss seen in row 2", "anomaly cosmic ray bit flip"],
        root_cause_hypothesis="error e_oom not present in data likely from memory leak.",
    )

    unsupported = validate(report, context)
    denominator = max(1, len(report.top_errors) + len(report.anomalies))
    grounding_score = max(0.0, 1.0 - (len(unsupported) / denominator))

    assert "error e_oom not present in data" in unsupported
    assert "anomaly cosmic ray bit flip" in unsupported
    assert grounding_score < 1.0


def test_grounding_false_positive_rate_stays_low_for_fully_supported_claims() -> None:
    validate = _load_validate_report_grounding()
    context = "error e_timeout seen in row 1; anomaly packet loss seen in row 2; retries exhausted"
    report = StubReport(
        top_errors=["error e_timeout seen in row 1"],
        anomalies=["anomaly packet loss seen in row 2"],
        root_cause_hypothesis="retries exhausted",
    )

    unsupported = validate(report, context)
    expected_supported_claims = len(report.top_errors) + len(report.anomalies) + 1
    false_positives = len(unsupported)
    false_positive_rate = false_positives / expected_supported_claims

    assert unsupported == []
    assert false_positive_rate == 0.0

    artifact_path = SERVER_ROOT / "tests" / "artifacts" / "responsible_ai_metrics.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {}
    if artifact_path.exists():
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    payload["suite"] = "responsible_ai_hardening"
    payload["grounding"] = {
        "supported_claims": expected_supported_claims,
        "false_positives": false_positives,
        "false_positive_rate": false_positive_rate,
        "true_negative_rate": 1.0,
    }
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
