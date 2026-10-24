import math
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.config import Settings
from app.models.local_tokenizer import LocalTokenizer


class EmbeddingGatewayError(RuntimeError):
    """A sanitized provider failure; no source text or credentials in messages."""


class CohereEmbeddingGateway:
    """Explicit Cohere calls with no implicit retries or model fallback.

    The batch runner will own retry counts. Constructing this adapter makes no
    requests, and tokenizer downloads never carry the Cohere Authorization header.
    """

    _BASE_URL = "https://api.cohere.com"

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        secret = settings.cohere_api_key
        if secret is None or not secret.get_secret_value().strip():
            raise ValueError("COHERE_API_KEY is required")
        if not settings.embedding_model.strip():
            raise ValueError("An embedding model is required")
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self._api_key = secret.get_secret_value()
        self._timeout = settings.embedding_timeout_seconds
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request_json(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                f"{self._BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingGatewayError(
                f"Cohere request failed (HTTP {exc.response.status_code})"
            ) from None
        except (httpx.HTTPError, ValueError):
            raise EmbeddingGatewayError("Cohere request failed or returned invalid JSON") from None
        if not isinstance(result, dict):
            raise EmbeddingGatewayError("Cohere returned an invalid response object")
        return result

    def load_tokenizer(self) -> LocalTokenizer:
        metadata = self._request_json("GET", f"/v1/models/{quote(self.model, safe='')}")
        if metadata.get("name") != self.model:
            raise EmbeddingGatewayError("Model metadata does not match the requested model")
        if metadata.get("is_deprecated") is True:
            raise EmbeddingGatewayError("The requested embedding model is deprecated")
        endpoints = metadata.get("endpoints")
        if not isinstance(endpoints, list) or "embed" not in endpoints:
            raise EmbeddingGatewayError("The requested model does not advertise the embed endpoint")
        tokenizer_url = metadata.get("tokenizer_url")
        if not isinstance(tokenizer_url, str) or not tokenizer_url:
            raise EmbeddingGatewayError("No matching local tokenizer is advertised for this model")
        try:
            parsed = urlsplit(tokenizer_url)
        except ValueError:
            raise EmbeddingGatewayError("The model advertised an invalid tokenizer URL") from None
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise EmbeddingGatewayError("The model advertised an invalid tokenizer URL")
        try:
            # Use a separate public client so injected/default authorization or
            # cookies cannot follow the tokenizer URL to a different host.
            with httpx.Client() as public_client:
                response = public_client.get(
                    tokenizer_url, timeout=self._timeout, follow_redirects=False
                )
                response.raise_for_status()
                tokenizer_json = response.text
        except httpx.HTTPError:
            raise EmbeddingGatewayError("The model's local tokenizer download failed") from None
        return LocalTokenizer(model=self.model, tokenizer_json=tokenizer_json)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, input_type="search_document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], input_type="search_query")[0]

    def _embed(self, texts: Sequence[str], *, input_type: str) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding inputs must not be empty or whitespace-only")
        result = self._request_json(
            "POST",
            "/v2/embed",
            payload={
                "model": self.model,
                "input_type": input_type,
                "inputs": [{"content": [{"type": "text", "text": text}]} for text in texts],
                "output_dimension": self.dimensions,
                "embedding_types": ["float"],
            },
        )
        embeddings = result.get("embeddings")
        vectors = embeddings.get("float") if isinstance(embeddings, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingGatewayError("Cohere returned an unexpected embedding count")
        validated = []
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise EmbeddingGatewayError("Cohere returned an unexpected vector dimension")
            if not all(self._valid_number(value) for value in vector):
                raise EmbeddingGatewayError("Cohere returned invalid vector values")
            validated.append([float(value) for value in vector])
        return validated

    @staticmethod
    def _valid_number(value: object) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False
