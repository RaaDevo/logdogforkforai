from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from lib.ai import get_generative_model, DEFAULT_MODEL, DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS
from lib.ai_prompting import build_hardened_system_prompt, wrap_untrusted_content
from parsers.few_shot_store import FewShotStore
from parsers.llm_contracts import (
    LlmInvocationResult,
    LlmSchemaResponse,
    LlmFormatDetectionResponse,
    LlmRecordResponse,
    LlmBatchExtractionResponse,
    TokenUsage,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

INPUT_PRICE_PER_M = 0.25
OUTPUT_PRICE_PER_M = 1.50

# Default per-instance budget for LLM parsing operations.
_DEFAULT_LLM_BUDGET_USD = 0.50
# Maximum number of LLM invocations per engine instance before forcing a stop.
_MAX_INVOCATIONS_PER_INSTANCE = 100


class LlmEngine:
    def __init__(
        self,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        budget_usd: float | None = None,
        few_shot_store: FewShotStore | None = None,
        profile_definition: dict[str, Any] | None = None,
    ):
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.budget_usd = budget_usd if budget_usd is not None else _DEFAULT_LLM_BUDGET_USD
        self.few_shot_store = few_shot_store or FewShotStore()
        self.profile_definition = profile_definition or {}
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0
        self._budget_exceeded = False
        self._invocation_count = 0

    @property
    def budget_exceeded(self) -> bool:
        if self.budget_usd is None:
            return False
        return self._budget_exceeded

    def _check_budget(self, estimated_cost: float) -> bool:
        if self.budget_usd is None:
            return True
        if self._total_cost_usd + estimated_cost > self.budget_usd:
            self._budget_exceeded = True
            return False
        return True

    def detect_format(
        self,
        sample_lines: list[str],
        few_shot_examples: list[str] | None = None,
        max_tokens: int | None = None,
        profile_context: dict[str, Any] | None = None,
    ) -> LlmInvocationResult:
        system_prompt = build_hardened_system_prompt(
            "You are an expert log format analyst. Analyze the provided log samples and detect the format, structural category, and recommended extraction strategy.",
            "Be precise and conservative with confidence scores.",
        )

        sample_text = "\n".join(line[:2000] for line in sample_lines[:50])
        prompt = (
            "Analyze these log lines and detect the format:\n\n"
            f"{wrap_untrusted_content(sample_text, label='Log lines')}"
        )

        merged_profile_context = dict(self.profile_definition)
        if profile_context:
            merged_profile_context.update(profile_context)
        if merged_profile_context:
            prompt = (
                f"{prompt}\n\n"
                "Profile hints for this dataset:\n"
                f"```json\n{_truncate_json(merged_profile_context, max_length=1200)}\n```"
            )

        if few_shot_examples is None:
            format_hint = str(merged_profile_context.get("detected_format", "unknown"))
            domain = str(merged_profile_context.get("domain", "unknown"))
            profile_name = merged_profile_context.get("name")
            few_shot_examples = self.few_shot_store.get_example_texts(
                format_name=format_hint,
                domain=domain,
                profile_name=str(profile_name) if isinstance(profile_name, str) else None,
                max_count=3,
            )

        if few_shot_examples:
            examples_text = "\n\n".join(
                f"Example {i + 1}:\n```\n{example[:1000]}\n```" for i, example in enumerate(few_shot_examples[:3])
            )
            prompt = f"{prompt}\n\nReference examples:\n\n{examples_text}"

        return self._invoke_structured(
            schema=LlmFormatDetectionResponse,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    def infer_schema(
        self,
        sample_lines: list[str],
        detected_format: str = "unknown",
        few_shot_schemas: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        profile_context: dict[str, Any] | None = None,
    ) -> LlmInvocationResult:
        system_prompt = build_hardened_system_prompt(
            "You are an expert log schema inference engine. Given sample log lines, infer a database schema that captures meaningful fields while minimizing null rates.",
            "Only include columns that appear in at least 50% of records. Use descriptive column names in snake_case.",
        )

        sample_text = "\n".join(line[:2000] for line in sample_lines[:50])
        prompt = (
            f"Detected format: {detected_format}\n\n"
            f"Infer a schema from these log lines:\n\n{wrap_untrusted_content(sample_text, label='Log lines')}\n\n"
            "Return column definitions with appropriate SQL types and descriptions."
        )

        merged_profile_context = dict(self.profile_definition)
        if profile_context:
            merged_profile_context.update(profile_context)
        if merged_profile_context:
            prompt = (
                f"{prompt}\n\n"
                "Profile schema expectations:\n"
                f"```json\n{_truncate_json(merged_profile_context, max_length=1400)}\n```"
            )

        if few_shot_schemas:
            schema_examples = "\n\n".join(
                f"Example schema {i + 1}:\n```json\n{_truncate_json(schema)}\n```"
                for i, schema in enumerate(few_shot_schemas[:3])
            )
            prompt = f"{prompt}\n\nReference schemas:\n\n{schema_examples}"

        return self._invoke_structured(
            schema=LlmSchemaResponse,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    def extract_record(
        self,
        line: str,
        column_names: list[str],
        column_descriptions: dict[str, str] | None = None,
        max_tokens: int | None = None,
    ) -> LlmInvocationResult:
        system_prompt = build_hardened_system_prompt(
            "You are a log field extraction engine. Extract the specified fields from a single log line.",
            "Return null for fields that cannot be found. Do not fabricate values.",
        )

        columns_desc = ", ".join(column_names)
        if column_descriptions:
            columns_detail = "\n".join(f"- {name}: {column_descriptions.get(name, '')}" for name in column_names)
            prompt = (
                f"Extract these fields from the log line:\n\n{columns_detail}\n\n"
                f"Log line:\n{wrap_untrusted_content(line[:3000], label='Log line')}\n\n"
                "Return extracted fields as key-value pairs."
            )
        else:
            prompt = (
                f"Extract these fields from the log line: {columns_desc}\n\n"
                f"Log line:\n{wrap_untrusted_content(line[:3000], label='Log line')}\n\n"
                "Return extracted fields as key-value pairs."
            )

        return self._invoke_structured(
            schema=LlmRecordResponse,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    def extract_batch(
        self,
        lines: list[str],
        column_names: list[str],
        column_descriptions: dict[str, str] | None = None,
        max_tokens: int | None = None,
    ) -> LlmInvocationResult:
        system_prompt = build_hardened_system_prompt(
            "You are a batch log extraction engine. Extract the specified fields from multiple log lines.",
            "Return null for fields that cannot be found. Do not fabricate values. Return one record per line.",
        )

        sample_text = "\n".join(f"Line {i + 1}: {line[:1000]}" for i, line in enumerate(lines[:20]))
        columns_desc = ", ".join(column_names)
        if column_descriptions:
            columns_detail = "\n".join(f"- {name}: {column_descriptions.get(name, '')}" for name in column_names)
            prompt = (
                f"Extract these fields from each log line:\n\n{columns_detail}\n\n"
                f"Log lines:\n\n{wrap_untrusted_content(sample_text, label='Log lines')}\n\n"
                "Return extracted records as a list of objects, one per line."
            )
        else:
            prompt = (
                f"Extract these fields from each log line: {columns_desc}\n\n"
                f"Log lines:\n\n{wrap_untrusted_content(sample_text, label='Log lines')}\n\n"
                "Return extracted records as a list of objects, one per line."
            )

        return self._invoke_structured(
            schema=LlmBatchExtractionResponse,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    def refine_schema(
        self,
        sample_lines: list[str],
        current_columns: list[dict[str, Any]],
        null_rates: dict[str, float],
        max_tokens: int | None = None,
    ) -> LlmInvocationResult:
        system_prompt = build_hardened_system_prompt(
            "You are a schema refinement engine. Given a current schema and null rates for each column, refine the schema to reduce null rates.",
            "Consider merging sparse columns, splitting overloaded columns, or renaming columns for better clarity.",
        )

        high_null = {k: v for k, v in null_rates.items() if v > 0.5}
        null_report = "\n".join(
            f"- {col}: {rate:.0%} null" for col, rate in sorted(high_null.items(), key=lambda x: -x[1])
        )
        current_schema = "\n".join(
            f"- {c['name']} ({c.get('sql_type', 'TEXT')}): {c.get('description', '')}" for c in current_columns
        )

        sample_text = "\n".join(line[:2000] for line in sample_lines[:30])
        prompt = (
            f"Current schema:\n{current_schema}\n\n"
            f"High null rate columns:\n{null_report}\n\n"
            f"Sample log lines:\n\n{wrap_untrusted_content(sample_text, label='Sample log lines')}\n\n"
            "Refine the schema to reduce null rates while preserving semantic meaning."
        )

        return self._invoke_structured(
            schema=LlmSchemaResponse,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    def _invoke_structured(
        self,
        schema: type[T],
        prompt: str,
        system_prompt: str,
        max_tokens: int | None = None,
        max_retries: int = 2,
    ) -> LlmInvocationResult:
        retry_count = 0
        last_error: str | None = None

        # Enforce per-instance invocation cap.
        if self._invocation_count >= _MAX_INVOCATIONS_PER_INSTANCE:
            return LlmInvocationResult(
                success=False,
                warning=f"LLM invocation limit reached ({_MAX_INVOCATIONS_PER_INSTANCE} calls per parse job).",
                retry_count=0,
            )

        estimated_input_tokens = len(prompt) // 4
        estimated_cost = estimated_input_tokens / 1_000_000 * INPUT_PRICE_PER_M + 500 / 1_000_000 * OUTPUT_PRICE_PER_M
        if not self._check_budget(estimated_cost):
            return LlmInvocationResult(
                success=False,
                warning=f"LLM budget exceeded (budget: ${self.budget_usd:.2f}, spent: ${self._total_cost_usd:.6f}).",
                retry_count=0,
            )

        while retry_count <= max_retries:
            try:
                generative_model = get_generative_model(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                )

                response = generative_model.generate_structured(
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                )

                input_tokens = len(prompt) // 4
                output_tokens = len(response.model_dump_json()) // 4
                total_tokens = input_tokens + output_tokens
                cost_usd = input_tokens / 1_000_000 * INPUT_PRICE_PER_M + output_tokens / 1_000_000 * OUTPUT_PRICE_PER_M

                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens
                self._total_cost_usd += cost_usd
                self._invocation_count += 1

                return LlmInvocationResult(
                    success=True,
                    response=response,
                    token_usage=TokenUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        estimated_cost_usd=cost_usd,
                    ),
                    retry_count=retry_count,
                )

            except Exception as error:
                last_error = str(error)
                retry_count += 1
                logger.warning(
                    "LLM invocation failed (attempt %d/%d): %s",
                    retry_count,
                    max_retries + 1,
                    last_error,
                )

                if retry_count <= max_retries:
                    prompt = (
                        f"{prompt}\n\n"
                        f"Previous attempt failed with: {last_error}\n"
                        "Please try again with a corrected response."
                    )

        return LlmInvocationResult(
            success=False,
            warning=f"LLM invocation failed after {max_retries + 1} attempts: {last_error}",
            retry_count=retry_count,
        )

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    def reset_cost_tracking(self) -> None:
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0

    def get_cost_summary(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_tokens": self._total_input_tokens + self._total_output_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
            "model": self.model,
        }


def _truncate_json(obj: Any, max_length: int = 500) -> str:
    import json

    text = json.dumps(obj, ensure_ascii=True, indent=2)
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
