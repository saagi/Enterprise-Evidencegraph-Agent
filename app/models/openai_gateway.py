from typing import TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from app.config import Settings


StructuredOutputT = TypeVar(
    "StructuredOutputT",
    bound=BaseModel,
)


class LLMGatewayError(RuntimeError):
    """Raised when structured LLM generation fails."""


class OpenAIGateway:
    """OpenAI implementation of the provider-independent LLM gateway."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise ValueError("LLM_API_KEY is required")

        self._model = settings.llm_model

        self._client = OpenAI(
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=system_prompt,
                input=user_prompt,
                text_format=output_model,
            )

        except OpenAIError as exc:
            raise LLMGatewayError(
                "OpenAI structured generation failed"
            ) from exc

        parsed = response.output_parsed

        if parsed is None:
            raise LLMGatewayError(
                "OpenAI returned no parsed structured output"
            )

        return parsed