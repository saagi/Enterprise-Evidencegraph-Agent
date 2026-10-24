import hashlib
from importlib import import_module
from typing import Any


class LocalTokenizerError(RuntimeError):
    """The selected model's local tokenizer could not be loaded."""


class LocalTokenizer:
    """Count input-text tokens locally, without model-added special tokens.

    Model association must come from that model's provider metadata, not from
    guessing another model's tokenizer. Keep the content hash for versioning.
    """

    def __init__(self, *, model: str, tokenizer_json: str) -> None:
        try:
            tokenizer_module = import_module("tokenizers")
        except ImportError:
            raise LocalTokenizerError(
                "Install the project's tokenizers dependency to enable local token counting"
            ) from None
        try:
            self._tokenizer: Any = tokenizer_module.Tokenizer.from_str(tokenizer_json)
        except Exception:
            raise LocalTokenizerError("The model's tokenizer configuration is invalid") from None
        self.model = model
        self.fingerprint = hashlib.sha256(tokenizer_json.encode("utf-8")).hexdigest()

    def count(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)
