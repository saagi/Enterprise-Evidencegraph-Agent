import json
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.models.cohere_embeddings import EmbeddingGatewayError
from scripts.check_embedding_compatibility import main


def configuration():
    return Settings(_env_file=None, cohere_api_key="secret-test-key")


def test_default_check_never_calls_provider(capsys):
    with (
        patch("scripts.check_embedding_compatibility.get_settings", return_value=configuration()),
        patch("scripts.check_embedding_compatibility.find_spec", return_value=object()),
        patch("scripts.check_embedding_compatibility.CohereEmbeddingGateway") as gateway,
    ):
        assert main([]) == 0
        gateway.assert_not_called()

    report = json.loads(capsys.readouterr().out)
    assert report["live_checks"] == "not_run"
    assert report["compatible"] is None
    assert "secret-test-key" not in json.dumps(report)


def test_live_success_requires_tokenizer_and_document_and_query_checks(capsys):
    gateway = MagicMock()
    gateway.load_tokenizer.return_value.count.return_value = 20
    gateway.load_tokenizer.return_value.fingerprint = "synthetic-fingerprint"
    gateway.embed_documents.return_value = [[0.25] * 1024]
    gateway.embed_query.return_value = [0.25] * 1024
    with (
        patch("scripts.check_embedding_compatibility.get_settings", return_value=configuration()),
        patch("scripts.check_embedding_compatibility.find_spec", return_value=object()),
        patch("scripts.check_embedding_compatibility.CohereEmbeddingGateway", return_value=gateway),
    ):
        assert main(["--live"]) == 0

    assert json.loads(capsys.readouterr().out)["compatible"] is True
    gateway.embed_documents.assert_called_once()
    gateway.embed_query.assert_called_once()
    gateway.close.assert_called_once()


def test_live_failure_reports_failure_and_closes_gateway(capsys):
    gateway = MagicMock()
    gateway.load_tokenizer.side_effect = EmbeddingGatewayError("No matching local tokenizer")
    with (
        patch("scripts.check_embedding_compatibility.get_settings", return_value=configuration()),
        patch("scripts.check_embedding_compatibility.find_spec", return_value=object()),
        patch("scripts.check_embedding_compatibility.CohereEmbeddingGateway", return_value=gateway),
    ):
        assert main(["--live"]) == 1

    assert json.loads(capsys.readouterr().out)["compatible"] is False
    gateway.embed_documents.assert_not_called()
    gateway.close.assert_called_once()


def test_missing_dependency_prevents_live_requests(capsys):
    with (
        patch("scripts.check_embedding_compatibility.get_settings", return_value=configuration()),
        patch("scripts.check_embedding_compatibility.find_spec", return_value=None),
        patch("scripts.check_embedding_compatibility.CohereEmbeddingGateway") as gateway,
    ):
        assert main(["--live"]) == 1
        gateway.assert_not_called()

    assert json.loads(capsys.readouterr().out)["live_checks"] == "not_run"
