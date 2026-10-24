import hashlib
from unittest.mock import patch

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from app.models.local_tokenizer import LocalTokenizer, LocalTokenizerError


@pytest.fixture
def tokenizer_json():
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "hello": 1, "world": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    return tokenizer.to_str()


def test_counts_tokens_locally_and_records_model_and_fingerprint(tokenizer_json):
    tokenizer = LocalTokenizer(model="synthetic-test-model", tokenizer_json=tokenizer_json)

    assert tokenizer.count("hello world") == 2
    assert tokenizer.count("") == 0
    assert tokenizer.model == "synthetic-test-model"
    assert tokenizer.fingerprint == hashlib.sha256(tokenizer_json.encode()).hexdigest()


def test_invalid_tokenizer_is_rejected_without_echoing_its_contents():
    with pytest.raises(LocalTokenizerError, match="configuration is invalid") as error:
        LocalTokenizer(model="test", tokenizer_json="SENSITIVE MALFORMED DATA")

    assert "SENSITIVE" not in str(error.value)


def test_missing_dependency_reports_how_to_enable_local_counting():
    with patch("app.models.local_tokenizer.import_module", side_effect=ImportError):
        with pytest.raises(LocalTokenizerError, match="Install.*tokenizers"):
            LocalTokenizer(model="test", tokenizer_json="{}")
