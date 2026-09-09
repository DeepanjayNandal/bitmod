"""Fuzzy matching — retrieval, scoring, and determinism.

Fuzzy match could not catch a typo at all, for two compounding reasons: the LIKE
pre-filter searched for the misspelled token so the candidate row was never
retrieved, and the scoring blended token overlap with edit distance so the
measure that recognised the typo was outvoted by the one that did not.

Backend-parameterised tests run real SQL. SQLite runs always; PostgreSQL and
MySQL are opt-in (see docker-compose.test.yml).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest
from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.cache_engine import fuzzy_prefilter_terms, fuzzy_similarity, normalize_query_fuzzy
from bitmod.interfaces.database import AnswerCacheRecord

USE_POSTGRES = os.getenv("BITMOD_TEST_POSTGRES", "0") == "1"
USE_MYSQL = os.getenv("BITMOD_TEST_MYSQL", "0") == "1"

STORED = "what is the refund policy"
FUZZY_THRESHOLD = 0.85

_BACKEND_IDS = ["sqlite"]
if USE_POSTGRES:
    _BACKEND_IDS.append("postgres")
if USE_MYSQL:
    _BACKEND_IDS.append("mysql")


@pytest.fixture(params=_BACKEND_IDS)
def backend(request):
    kind = request.param
    if kind == "sqlite":
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.initialize()
        yield be
        if os.path.exists(path):
            os.unlink(path)
        return

    from sqlalchemy import text

    if kind == "postgres":
        from bitmod.adapters.db_postgresql import PostgreSQLBackend

        be = PostgreSQLBackend(os.environ["DATABASE_URL"])
        with be._engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        from bitmod.adapters.db_mysql import MySQLBackend

        be = MySQLBackend(os.environ["MYSQL_URL"])
        with be._engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for (table,) in conn.execute(text("SHOW TABLES")).fetchall():
                conn.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    be.initialize()
    yield be


@pytest.fixture
def seeded(backend):
    with backend.session() as session:
        backend.cache_store(
            session,
            AnswerCacheRecord(
                id="c1",
                answer_key="k1",
                question_raw=STORED,
                question_normalized=normalize_query_fuzzy(STORED),
                answer_text="Refunds take five business days.",
                source_sections=[],
            ),
        )
    return backend


def _matches(backend, query: str, threshold: float = FUZZY_THRESHOLD) -> int:
    with backend.session() as session:
        return len(
            backend.cache_fuzzy_match(session, normalize_query_fuzzy(query), {}, threshold=threshold, max_results=5)
        )


# ---------------------------------------------------------------------------
# Typos are found; unrelated queries are not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "what is the refund pollicy",  # doubled letter
        "what is the refund polcy",  # dropped letter
        "waht is the refund policy",  # transposition
    ],
)
def test_typos_match(seeded, query):
    """REGRESSION GUARD — the typo has to survive both the filter and the score.

    Two separate failures had to be fixed for this to pass, and either one
    reappearing breaks it:

    - the LIKE pre-filter searched for the *longest* token, which is the
      misspelled one, so the row was never retrieved to be scored at all
    - scoring blended token overlap with edit distance, and a misspelled word
      reads as a different token, so the 60%-weighted measure outvoted the 40%
      one that had scored the pair correctly
    """
    assert _matches(seeded, query) == 1, f"{query!r} is a typo of the cached query and should match"


@pytest.mark.parametrize(
    "query",
    [
        "how do i track my shipment",
        "what are the shipping costs",
        "can i change my delivery address",
        "who is the account manager",
    ],
)
def test_unrelated_queries_do_not_match(seeded, query):
    """The looser scorer must not turn fuzzy match into a wildcard."""
    assert _matches(seeded, query) == 0, f"{query!r} is unrelated and must not match"


def test_rephrasings_still_match(seeded):
    """max() must not cost the rephrasing cases the blend was tuned for."""
    assert _matches(seeded, "what is the policy for refunds") == 1


# ---------------------------------------------------------------------------
# The margin, so a future weighting change shows its cost
# ---------------------------------------------------------------------------


def test_margin_between_worst_pass_and_best_fail():
    """Anyone changing the scoring should see what headroom they are spending.

    The gap is wide — nothing sits near the threshold — so the exact value of
    0.85 is not load-bearing. That is a property worth keeping.
    """
    stored = normalize_query_fuzzy(STORED)
    passing = [
        "what is the refund pollicy",
        "what is the refund polcy",
        "waht is the refund policy",
        "what is the policy for refunds",
        "refund policy",
    ]
    failing = [
        "how do i track my shipment",
        "what are the shipping costs",
        "can i change my delivery address",
        "who is the account manager",
    ]
    worst_pass = min(fuzzy_similarity(normalize_query_fuzzy(q), stored) for q in passing)
    best_fail = max(fuzzy_similarity(normalize_query_fuzzy(q), stored) for q in failing)

    assert worst_pass >= FUZZY_THRESHOLD, f"a case that should pass scores {worst_pass:.3f}"
    assert best_fail < FUZZY_THRESHOLD, f"a case that should fail scores {best_fail:.3f}"
    assert worst_pass - best_fail > 0.5, (
        f"margin collapsed to {worst_pass - best_fail:.3f} (worst pass {worst_pass:.3f}, "
        f"best fail {best_fail:.3f}) — the threshold is now load-bearing"
    )


def test_known_boundary_case_refnud_does_not_match(seeded):
    """A documented limit, not a surprise.

    'refnud' scores 0.846 against a 0.85 threshold — just under. Lowering the
    threshold to 0.84 would catch this one case and shrink a clean margin for no
    principled reason, so it is left failing deliberately.
    """
    score = fuzzy_similarity(normalize_query_fuzzy("what is the refnud policy"), normalize_query_fuzzy(STORED))
    assert 0.84 < score < FUZZY_THRESHOLD, f"boundary moved: refnud now scores {score:.4f}"
    assert _matches(seeded, "what is the refnud policy") == 0


# ---------------------------------------------------------------------------
# Determinism — the pre-filter must not depend on hash randomisation
# ---------------------------------------------------------------------------


def test_prefilter_order_is_deterministic_within_a_process():
    """Equal-length tokens must not be ordered by set iteration."""
    query = normalize_query_fuzzy("what is the refnud policy")  # 'policy' and 'refnud' both 6 chars
    first = fuzzy_prefilter_terms(query)
    for _ in range(50):
        assert fuzzy_prefilter_terms(query) == first


def test_prefilter_order_is_deterministic_across_processes():
    """REGRESSION GUARD — this was flaky, and silently so.

    Sorting a set by length alone leaves equal-length tokens in set-iteration
    order, which varies per process because Python randomises string hashing.
    The same query could retrieve a different candidate set on different runs,
    so a cache lookup hit or missed depending on which worker served it — and
    any benchmark built on it would be unreproducible.

    Separate interpreters with different PYTHONHASHSEED values are the only way
    to catch this; within one process it always looks fine.
    """
    script = (
        "import sys; sys.path.insert(0, 'core');"
        "from bitmod.cache_engine import fuzzy_prefilter_terms, normalize_query_fuzzy;"
        "print(fuzzy_prefilter_terms(normalize_query_fuzzy('what is the refnud policy')))"
    )
    seen = set()
    for seed in ("0", "1", "42", "1337", "99999"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
        )
        seen.add(out.stdout.strip())
    assert len(seen) == 1, f"pre-filter order varies with PYTHONHASHSEED: {seen}"


def test_fuzzy_threshold_changes_matching_behaviour(seeded):
    """The threshold has to alter outcomes, not merely be readable.

    'refnud' scores 0.846: above a 0.80 threshold, below the 0.85 default.
    """
    assert _matches(seeded, "what is the refnud policy", threshold=0.85) == 0
    assert _matches(seeded, "what is the refnud policy", threshold=0.80) == 1


def test_prefix_length_changes_which_candidates_are_retrieved():
    """A longer prefix is more selective and stops tolerating early typos."""
    query = normalize_query_fuzzy("what is the refund pollicy")
    assert fuzzy_prefilter_terms(query, prefix_length=3) == ["pol", "ref"]
    assert fuzzy_prefilter_terms(query, prefix_length=7) == ["pollicy", "refund"]


def test_pipeline_grades_fuzzy_confidence_by_similarity(seeded):
    """The layer's confidence has to track how similar the match actually is.

    The pipeline added a flat cache_cfg.fuzzy_confidence (0.40) for every fuzzy
    hit, so a one-character typo and a match that scraped over the threshold
    carried identical weight. The graduated curve already existed in
    _similarity_to_confidence — it was simply never called.

    Asserting on that function alone would pass without the fix, since the curve
    was never the broken part. This drives the pipeline and reads the confidence
    it actually attached.
    """
    from bitmod.cache_engine import _similarity_to_confidence
    from bitmod.proxy import BitmodProxy
    from bitmod.router import LLMRouter

    proxy = BitmodProxy(backend=seeded, llm_router=LLMRouter(primary=None), default_model="test")

    def fuzzy_evidence(query: str):
        result = proxy._run_cache_pipeline(query, [{"role": "user", "content": query}])
        return [e for e in (result.evidence.evidences or []) if e.layer == "fuzzy"]

    near = fuzzy_evidence("what is the refund pollicy")
    assert near, "expected the typo to produce fuzzy evidence"

    for item in near:
        assert item.confidence == pytest.approx(_similarity_to_confidence(item.similarity, "fuzzy")), (
            f"fuzzy confidence {item.confidence} does not follow from similarity {item.similarity} — "
            "the layer is still adding a flat constant"
        )

    flat = {round(e.confidence, 6) for e in near}
    assert flat != {0.40}, "fuzzy is still contributing the flat 0.40 regardless of similarity"


def test_fuzzy_match_carries_the_score_it_was_filtered_on(seeded):
    """The adapters score every candidate and used to return bare records.

    Without the score the pipeline cannot grade anything, which is why the flat
    constant was there in the first place.
    """
    from bitmod.cache_engine import fuzzy_match

    with seeded.session() as session:
        matches = fuzzy_match(seeded, session, "what is the refnud policy", similarity_threshold=0.80)

    assert matches, "expected the typo to match"
    assert all(hasattr(m, "record") and hasattr(m, "similarity") for m in matches)
    assert all(m.similarity >= 0.80 for m in matches), "returned a match below the threshold it was given"
