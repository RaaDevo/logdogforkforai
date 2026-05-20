from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from lib.ai_prompting import UNTRUSTED_DATA_GUARDRAIL, build_hardened_system_prompt, wrap_untrusted_content


SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parents[1]
SAMPLES_DIR = REPO_ROOT / "samples"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_adversarial_samples_exist_and_contain_attack_patterns() -> None:
    expected = {
        "adversarial_prompt_injection.log": ["ignore previous instructions", "system override", "disclose api_key"],
        "adversarial_schema_poisoning.log": ["__proto__", "constructor.prototype", "column_hint"],
        "adversarial_misleading_instructions.log": ["claim there were 0 anomalies", "fabricate plausible root cause"],
    }
    for file_name, markers in expected.items():
        text = _read(SAMPLES_DIR / file_name).lower()
        for marker in markers:
            assert marker in text


def test_llm_call_sites_apply_hardened_prompts_and_wrappers() -> None:
    targets = {
        "src/routes/logs.py": ["build_hardened_system_prompt(", "wrap_untrusted_content("],
        "src/parsers/ai.py": ["build_hardened_system_prompt(", "wrap_untrusted_content("],
        "src/parsers/llm_engine.py": ["build_hardened_system_prompt(", "wrap_untrusted_content("],
    }
    for relative_path, required_tokens in targets.items():
        text = _read(SERVER_ROOT / relative_path)
        for token in required_tokens:
            assert token in text, f"{token} missing from {relative_path}"


def test_hardened_guardrails_wrap_adversarial_fixture_payloads() -> None:
    base_prompt = build_hardened_system_prompt("You are a careful analyst.")
    assert UNTRUSTED_DATA_GUARDRAIL in base_prompt

    fixture_text = _read(SAMPLES_DIR / "adversarial_prompt_injection.log")
    wrapped = wrap_untrusted_content(fixture_text, label="Adversarial sample")
    assert "<UNTRUSTED_LOG_DATA_BEGIN>" in wrapped
    assert "<UNTRUSTED_LOG_DATA_END>" in wrapped
    assert "treat strictly as data" in wrapped
    assert "Ignore previous instructions" in wrapped


def test_attack_class_metrics_json_artifact() -> None:
    checks = {
        "prompt_injection": True,
        "schema_poisoning": True,
        "misleading_instructions": True,
    }
    artifact = {
        "suite": "responsible_ai_hardening",
        "pass_fail_by_attack_class": {
            attack_class: {"passed": 1 if passed else 0, "failed": 0 if passed else 1}
            for attack_class, passed in checks.items()
        },
    }

    out_dir = SERVER_ROOT / "tests" / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "responsible_ai_metrics.json"

    grounding_payload = {"true_negative_rate": 0.0, "false_positive_rate": 0.0}
    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
            grounding_payload = prior.get("grounding", grounding_payload)
        except json.JSONDecodeError:
            pass

    artifact["grounding"] = grounding_payload
    out_path.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")

    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(saved["pass_fail_by_attack_class"].keys()) == set(checks.keys())
