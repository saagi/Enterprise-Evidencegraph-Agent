import json
from unittest.mock import patch

import httpx
import pytest

from app.config import Settings
from app.models.cohere_embeddings import CohereEmbeddingGateway, EmbeddingGatewayError


def settings(**updates):
    return Settings(_env_file=None, cohere_api_key="secret-test-key", **updates)


def gateway_with_handler(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return CohereEmbeddingGateway(settings(), client=client)


def test_documents_and_queries_use_correct_roles_dimensions_and_exact_text():
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        vectors = [[0.25] * 1024] * len(payload["inputs"])
        return httpx.Response(200, json={"embeddings": {"float": vectors}})

    gateway = gateway_with_handler(handler)
    documents = gateway.embed_documents(["Source: Jira\n\nOriginal text", "Other input"])
    query = gateway.embed_query("Why did it fail?")

    assert len(documents) == 2
    assert len(query) == 1024
    document_payload = json.loads(requests[0].content)
    query_payload = json.loads(requests[1].content)
    assert document_payload == {
        "model": "embed-v5.0-fast",
        "input_type": "search_document",
        "inputs": [
            {"content": [{"type": "text", "text": "Source: Jira\n\nOriginal text"}]},
            {"content": [{"type": "text", "text": "Other input"}]},
        ],
        "output_dimension": 1024,
        "embedding_types": ["float"],
    }
    assert query_payload["input_type"] == "search_query"
    assert requests[0].headers["authorization"] == "Bearer secret-test-key"
    assert str(requests[0].url) == "https://api.cohere.com/v2/embed"


@pytest.mark.parametrize("status", [401, 429, 503])
def test_http_failures_are_sanitized_and_not_retried(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="secret-test-key private source text")

    with pytest.raises(EmbeddingGatewayError, match=f"HTTP {status}") as error:
        gateway_with_handler(handler).embed_query("private source text")

    assert len(requests) == 1
    assert "secret-test-key" not in str(error.value)
    assert "private source" not in str(error.value)


@pytest.mark.parametrize("vectors", [[], [[0.1] * 512], [[True] * 1024], [["bad"] * 1024]])
def test_malformed_vectors_are_rejected(vectors):
    gateway = gateway_with_handler(
        lambda request: httpx.Response(200, json={"embeddings": {"float": vectors}})
    )

    with pytest.raises(EmbeddingGatewayError):
        gateway.embed_query("test")


def test_nonfinite_values_are_rejected():
    gateway = gateway_with_handler(
        lambda request: httpx.Response(200, content=b'{"embeddings":{"float":[[NaN]]}}')
    )
    gateway.dimensions = 1

    with pytest.raises(EmbeddingGatewayError, match="invalid vector values"):
        gateway.embed_query("test")


def test_invalid_json_is_sanitized():
    gateway = gateway_with_handler(lambda request: httpx.Response(200, text="secret-test-key"))

    with pytest.raises(EmbeddingGatewayError, match="invalid JSON"):
        gateway.embed_query("test")


def test_empty_batch_and_blank_inputs_do_not_call_provider():
    def handler(request):
        pytest.fail("Provider must not be called")

    gateway = gateway_with_handler(handler)
    assert gateway.embed_documents([]) == []
    with pytest.raises(ValueError, match="whitespace-only"):
        gateway.embed_query("  ")


def test_missing_key_does_not_create_client():
    with patch("app.models.cohere_embeddings.httpx.Client") as client:
        with pytest.raises(ValueError, match="COHERE_API_KEY"):
            CohereEmbeddingGateway(Settings(_env_file=None, cohere_api_key=None))
        client.assert_not_called()


def test_key_is_redacted_in_settings():
    configuration = settings()
    assert "secret-test-key" not in repr(configuration)
    assert "secret-test-key" not in configuration.model_dump_json()


@pytest.mark.parametrize(
    "metadata",
    [
        {"name": "other-model", "endpoints": ["embed"]},
        {"name": "embed-v5.0-fast", "endpoints": ["chat"]},
        {"name": "embed-v5.0-fast", "endpoints": None},
        {"name": "embed-v5.0-fast", "endpoints": ["embed"]},
        {"name": "embed-v5.0-fast", "endpoints": ["embed"], "is_deprecated": True},
        {"name": "embed-v5.0-fast", "endpoints": ["embed"], "tokenizer_url": "http://example.org/t.json"},
        {"name": "embed-v5.0-fast", "endpoints": ["embed"], "tokenizer_url": "https://[broken"},
    ],
)
def test_incompatible_or_missing_tokenizer_metadata_never_falls_back(metadata):
    gateway = gateway_with_handler(lambda request: httpx.Response(200, json=metadata))

    with pytest.raises(EmbeddingGatewayError):
        gateway.load_tokenizer()


def test_public_tokenizer_download_does_not_receive_provider_credentials():
    metadata = {
        "name": "embed-v5.0-fast",
        "endpoints": ["embed"],
        "tokenizer_url": "https://tokenizers.example.org/config.json",
    }
    gateway = gateway_with_handler(lambda request: httpx.Response(200, json=metadata))
    public_requests = []

    def public_handler(request):
        public_requests.append(request)
        return httpx.Response(200, text="synthetic-tokenizer-json")

    public_client = httpx.Client(transport=httpx.MockTransport(public_handler))
    with patch("app.models.cohere_embeddings.httpx.Client", return_value=public_client):
        with patch("app.models.cohere_embeddings.LocalTokenizer") as tokenizer:
            assert gateway.load_tokenizer() is tokenizer.return_value
            tokenizer.assert_called_once_with(
                model="embed-v5.0-fast", tokenizer_json="synthetic-tokenizer-json"
            )
    assert "authorization" not in public_requests[0].headers
