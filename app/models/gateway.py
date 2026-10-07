from typing import Protocol, TypeVar

from pydantic import BaseModel


StructuredOutputT = TypeVar(
    "StructuredOutputT",
    bound=BaseModel,
)


class LLMGateway(Protocol):
    """Provider-independent interface for structured LLM generation."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        ...