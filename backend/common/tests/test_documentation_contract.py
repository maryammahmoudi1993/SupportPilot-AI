"""Phase 14 (Section 46): lightweight regression tests that protect real
documentation contracts — not brittle prose assertions, just the handful
of claims that would actively mislead a reader (or a Phase 18 frontend
implementer) if they silently went stale."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_DOCS = [
    REPO_ROOT / "docs" / "api" / "frontend-integration.md",
    REPO_ROOT / "docs" / "operations" / "deployment.md",
    REPO_ROOT / "docs" / "adr" / "0010-api-v1-contract-and-operational-boundary.md",
]

# A document is exempt from the "no exactly-once claim" scan when the
# phrase demonstrably refers to a single in-process computation (a Python
# call happening once, a metric registered once) rather than a distributed
# delivery guarantee — every current exemption is a documented, deliberate
# false positive, not a loophole.
_EXACTLY_ONCE_ALLOWED_CONTEXTS = (
    "never exactly-once",
    "never exactly once",
    "not exactly-once",
    "not exactly once",
)


@pytest.mark.parametrize("path", REQUIRED_DOCS, ids=lambda p: p.name)
def test_required_documentation_file_exists_and_is_non_trivial(path: Path):
    assert path.exists(), f"required Phase 14 doc missing: {path}"
    assert path.stat().st_size > 500, f"{path} looks too small to be real content"


def test_frontend_integration_doc_references_the_real_api_prefix():
    text = (REPO_ROOT / "docs" / "api" / "frontend-integration.md").read_text(encoding="utf-8")
    assert "/api/v1/" in text
    # It must also name the real auth endpoints, not a guessed shape.
    for endpoint in ("/api/v1/auth/login/", "/api/v1/auth/refresh/", "/api/v1/auth/csrf/"):
        assert endpoint in text


def test_frontend_integration_doc_documents_the_stable_error_envelope():
    text = (REPO_ROOT / "docs" / "api" / "frontend-integration.md").read_text(encoding="utf-8")
    for code in (
        "validation_error",
        "authentication_failed",
        "permission_denied",
        "not_found",
        "rate_limited",
        "service_unavailable",
    ):
        assert code in text


@pytest.mark.parametrize(
    "doc_path",
    [
        REPO_ROOT / "docs" / "operations" / "deployment.md",
        REPO_ROOT / "docs" / "adr" / "0010-api-v1-contract-and-operational-boundary.md",
    ],
    ids=lambda p: p.name,
)
def test_no_document_claims_distributed_exactly_once_delivery(doc_path: Path):
    # Regression (Phase 14, Section 40) — scoped to the two documents this
    # phase authors directly: every "exactly once"/"exactly-once" mention
    # in them must explicitly deny it, never assert it as a real network
    # delivery guarantee. The pre-existing docs/architecture/*.md and
    # docs/adr/0001-0009 corpus was manually audited once (Milestone 4) —
    # every mention there is either an explicit denial or a legitimate
    # non-delivery use (e.g. "the gate runs exactly once" describing
    # in-process idempotency) that a blind keyword scan cannot reliably
    # tell apart from a delivery claim, so it is not re-scanned here.
    text = doc_path.read_text(encoding="utf-8").lower()
    for needle in ("exactly once", "exactly-once"):
        start = 0
        while True:
            hit = text.find(needle, start)
            if hit == -1:
                break
            window = text[max(0, hit - 40) : hit + len(needle) + 10]
            assert any(allowed in window for allowed in _EXACTLY_ONCE_ALLOWED_CONTEXTS), (
                f"{doc_path}: an 'exactly once' mention near {window!r} does not read as "
                "a denial — verify it isn't a false distributed-delivery guarantee."
            )
            start = hit + len(needle)
