"""Check local readiness; --live explicitly probes Cohere using synthetic text."""

import argparse
import json
from collections.abc import Sequence
from importlib.util import find_spec

from app.config import get_settings
from app.models.cohere_embeddings import CohereEmbeddingGateway, EmbeddingGatewayError
from app.models.local_tokenizer import LocalTokenizerError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true",
        help="Make provider requests and download the selected model's tokenizer",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    secret = settings.cohere_api_key
    key_present = bool(secret is not None and secret.get_secret_value().strip())
    tokenizer_available = find_spec("tokenizers") is not None
    report: dict[str, object] = {
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "api_key_present": key_present,
        "local_tokenizer_dependency_installed": tokenizer_available,
        "live_checks": "not_run",
        "compatible": None,
    }
    if not args.live:
        print(json.dumps(report, indent=2))
        return 0 if key_present and tokenizer_available else 1
    if not key_present or not tokenizer_available:
        report["error"] = "Configure COHERE_API_KEY and install project dependencies first"
        print(json.dumps(report, indent=2))
        return 1

    gateway = CohereEmbeddingGateway(settings)
    try:
        tokenizer = gateway.load_tokenizer()
        sample = (
            "Source: Jira\nTitle: Synthetic connection check\n"
            "Section: Description\n\nTest input."
        )
        token_count = tokenizer.count(sample)
        if not 0 < token_count <= 512:
            raise LocalTokenizerError("Synthetic sample produced an invalid local token count")
        document = gateway.embed_documents([sample])[0]
        query = gateway.embed_query("Synthetic connection check")
        report.update({
            "live_checks": "passed",
            "compatible": True,
            "tokenizer_fingerprint": tokenizer.fingerprint,
            "sample_token_count": token_count,
            "document_dimensions": len(document),
            "query_dimensions": len(query),
        })
    except (EmbeddingGatewayError, LocalTokenizerError, ValueError) as exc:
        report.update({"live_checks": "failed", "compatible": False, "error": str(exc)})
    finally:
        gateway.close()
    print(json.dumps(report, indent=2))
    return 0 if report["compatible"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
