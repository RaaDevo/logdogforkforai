from typing import TypeVar

from langchain_openrouter import ChatOpenRouter
from pydantic import BaseModel

from environment import OPENROUTER_API_KEY, OPENROUTER_TITLE, OPENROUTER_REFERER, OPENROUTER_MODEL

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = OPENROUTER_MODEL.get_secret_value()
DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 2048


class GenerativeModel:
    def __init__(
        self,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int | None = DEFAULT_MAX_TOKENS,
    ):
        resolved_model = model or DEFAULT_MODEL
        self.client = ChatOpenRouter(
            model=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=OPENROUTER_API_KEY.get_secret_value(),
            app_title=OPENROUTER_TITLE.get_secret_value(),
            app_url=OPENROUTER_REFERER.get_secret_value(),
        )

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("human", prompt))

        response = self.client.invoke(messages)
        return response.content

    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
    ) -> T:
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("human", prompt))

        structured_client = self.client.with_structured_output(schema, method="json_schema")
        return structured_client.invoke(messages)


def get_generative_model(
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int | None = DEFAULT_MAX_TOKENS,
) -> GenerativeModel:
    return GenerativeModel(model=model, temperature=temperature, max_tokens=max_tokens)
