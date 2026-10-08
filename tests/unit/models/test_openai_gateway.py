from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError

from app.config import Settings
from app.domain.models import RelationshipType
from app.domain.services import (
    ExtractedRelationship,
    RelationshipExtractionOutput,
)
from app.models.openai_gateway import (
    LLMGatewayError,
    OpenAIGateway,
)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="test-api-key",
        llm_model="gpt-5-mini",
    )


def make_relationship_output() -> RelationshipExtractionOutput:
    return RelationshipExtractionOutput(
        relationships=[
            ExtractedRelationship(
                source_mention="PAY-1842",
                target_mention="PR #829",
                relationship_type=RelationshipType.IMPLEMENTED_BY,
                confidence=0.96,
                evidence_text="Fix is being implemented in PR #829.",
            )
        ]
    )


@patch("app.models.openai_gateway.OpenAI")
def test_generate_structured_returns_parsed_output(
    mock_openai_class: MagicMock,
) -> None:
    expected_output = make_relationship_output()

    mock_client = mock_openai_class.return_value
    mock_client.responses.parse.return_value.output_parsed = expected_output

    gateway = OpenAIGateway(make_settings())

    result = gateway.generate_structured(
        system_prompt="Extract relationships.",
        user_prompt="Fix is being implemented in PR #829.",
        output_model=RelationshipExtractionOutput,
    )

    assert result == expected_output

    mock_client.responses.parse.assert_called_once_with(
        model="gpt-5-mini",
        instructions="Extract relationships.",
        input="Fix is being implemented in PR #829.",
        text_format=RelationshipExtractionOutput,
    )


def test_missing_api_key_raises_error() -> None:
    settings = Settings(
        _env_file=None,
        llm_api_key=None,
    )

    with pytest.raises(ValueError, match="LLM_API_KEY is required"):
        OpenAIGateway(settings)


@patch("app.models.openai_gateway.OpenAI")
def test_empty_parsed_output_raises_error(
    mock_openai_class: MagicMock,
) -> None:
    mock_client = mock_openai_class.return_value
    mock_client.responses.parse.return_value.output_parsed = None

    gateway = OpenAIGateway(make_settings())

    with pytest.raises(
        LLMGatewayError,
        match="no parsed structured output",
    ):
        gateway.generate_structured(
            system_prompt="Extract relationships.",
            user_prompt="Some enterprise discussion.",
            output_model=RelationshipExtractionOutput,
        )


@patch("app.models.openai_gateway.OpenAI")
def test_api_failure_raises_gateway_error(
    mock_openai_class: MagicMock,
) -> None:
    mock_client = mock_openai_class.return_value

    mock_client.responses.parse.side_effect = APIConnectionError(
        request=MagicMock()
    )

    gateway = OpenAIGateway(make_settings())

    with pytest.raises(
        LLMGatewayError,
        match="OpenAI structured generation failed",
    ):
        gateway.generate_structured(
            system_prompt="Extract relationships.",
            user_prompt="Fix is being implemented in PR #829.",
            output_model=RelationshipExtractionOutput,
        )