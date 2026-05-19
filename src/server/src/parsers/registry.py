from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parsers.contracts import (
        ClassificationResult,
        FileParserSelection,
        ParserPipelineResult,
        ParserSupportRequest,
        ParserSupportResult,
    )
    from parsers.preprocessor import FileInput

logger = logging.getLogger(__name__)


class ParserPipeline(ABC):
    parser_key: str = ""

    @abstractmethod
    def parse(
        self,
        file_inputs: list["FileInput"],
        classification: "ClassificationResult",
    ) -> "ParserPipelineResult": ...

    @abstractmethod
    def supports(self, request: "ParserSupportRequest") -> "ParserSupportResult": ...

    def ingest(
        self,
        file_inputs: list["FileInput"],
        classification: "ClassificationResult",
    ) -> "ParserPipelineResult":
        return self.parse(file_inputs, classification)


class _ParserRegistry:
    def __init__(self) -> None:
        self._pipelines: dict[str, ParserPipeline] = {}
        self._fallback_order = {"unified": 0}
        self._discovery_done = False

    def register(self, pipeline: ParserPipeline) -> None:
        if not pipeline.parser_key:
            raise ValueError("parser_key must be set for parser pipeline registration")

        if pipeline.parser_key in self._pipelines:
            logger.warning("Overwriting parser pipeline for key '%s'.", pipeline.parser_key)

        self._pipelines[pipeline.parser_key] = pipeline
        logger.debug("Registered parser pipeline: %s", pipeline.parser_key)

    def route(self, parser_key: str) -> ParserPipeline:
        self.discover()
        if parser_key not in self._pipelines:
            raise KeyError(
                f"No parser pipeline registered for key '{parser_key}'. Registered keys: {sorted(self._pipelines)}"
            )
        return self._pipelines[parser_key]

    def registered_keys(self) -> list[str]:
        self.discover()
        return list(self._pipelines.keys())

    def support_for_file(
        self,
        file_input: "FileInput",
        mime_type: str | None = None,
    ) -> list["ParserSupportResult"]:
        self.discover()
        from parsers.contracts import ParserSupportRequest, ParserSupportResult

        request = ParserSupportRequest(
            file_id=file_input.file_id,
            filename=file_input.filename,
            content=file_input.content,
            mime_type=mime_type,
        )

        results: list[ParserSupportResult] = []
        for parser_key, pipeline in self._pipelines.items():
            try:
                result = pipeline.supports(request)
            except Exception as error:  # noqa: BLE001
                logger.warning("supports() failed for parser '%s': %s", parser_key, error)
                result = ParserSupportResult(
                    parser_key=parser_key,
                    supported=False,
                    score=0.0,
                    reasons=[f"Support check failed: {error}"],
                )
            results.append(result)

        return sorted(
            results,
            key=lambda item: (
                1 if item.supported else 0,
                item.score,
                -self._fallback_order.get(item.parser_key, 99),
            ),
            reverse=True,
        )

    def resolve_for_files(
        self,
        file_inputs: list["FileInput"],
        mime_types_by_file_id: dict[str, str] | None = None,
        preferred_keys: list[str] | None = None,
    ) -> tuple[dict[str, list["FileInput"]], list["FileParserSelection"], list[str]]:
        self.discover()
        from parsers.contracts import FileParserSelection

        grouped: dict[str, list[FileInput]] = {}
        selections: list[FileParserSelection] = []
        warnings: list[str] = []
        preferred_rank = {key: index for index, key in enumerate(preferred_keys or [])}

        for file_input in file_inputs:
            mime_type: str | None = None
            if mime_types_by_file_id and file_input.file_id:
                mime_type = mime_types_by_file_id.get(file_input.file_id)

            ranked = self.support_for_file(file_input=file_input, mime_type=mime_type)
            if not ranked:
                warnings.append(f"No parsers registered for '{file_input.filename}'.")
                continue

            def _sort_key(item: "ParserSupportResult") -> tuple[int, float, int, int]:
                preferred_pos = preferred_rank.get(item.parser_key, 999)
                fallback_pos = self._fallback_order.get(item.parser_key, 99)
                return (
                    1 if item.supported else 0,
                    item.score,
                    -preferred_pos,
                    -fallback_pos,
                )

            best = sorted(ranked, key=_sort_key, reverse=True)[0]

            if not best.supported:
                warnings.append(
                    f"No parser strongly supports '{file_input.filename}', using '{best.parser_key}' fallback "
                    f"(score={best.score:.2f})."
                )

            grouped.setdefault(best.parser_key, []).append(file_input)
            selections.append(
                FileParserSelection(
                    file_id=file_input.file_id,
                    filename=file_input.filename,
                    parser_key=best.parser_key,
                    score=best.score,
                    reasons=best.reasons,
                )
            )

        return grouped, selections, warnings

    def discover(self, force: bool = False) -> None:
        if self._discovery_done and not force:
            return

        if force:
            self._pipelines.clear()

        try:
            from parsers.deterministic import (
                ApacheAccessPipeline,
                BinaryHexPipeline,
                CsvPipeline,
                JsonLinesPipeline,
                KeyValuePipeline,
                LogfmtPipeline,
                NginxAccessPipeline,
                SectionedKeyValuePipeline,
                SyslogPipeline,
                TimestampedEventTextPipeline,
                XmlPipeline,
            )

            # Structured formats first (higher priority)
            self.register(JsonLinesPipeline())
            self.register(XmlPipeline())
            self.register(CsvPipeline())
            self.register(SectionedKeyValuePipeline())
            self.register(TimestampedEventTextPipeline())
            # Semi-structured / unstructured formats
            self.register(SyslogPipeline())
            self.register(ApacheAccessPipeline())
            self.register(NginxAccessPipeline())
            self.register(LogfmtPipeline())
            self.register(KeyValuePipeline())
            self.register(BinaryHexPipeline())
        except Exception as error:  # noqa: BLE001
            logger.warning("Could not register deterministic pipelines: %s", error)

        try:
            from parsers.unified.pipeline import UnifiedPipeline

            self.register(UnifiedPipeline())
        except Exception as error:  # noqa: BLE001
            logger.warning("Could not register unified pipeline: %s", error)

        self._discovery_done = True


ParserRegistry = _ParserRegistry()
