"""Tests for pipeline evidence accumulation and atomic fact decomposition."""

from __future__ import annotations

import pytest
from bitmod.cache_engine import (
    CacheEvidence,
    PipelineEvidence,
    SemanticMatch,
    _get_config,
    _similarity_to_confidence,
    decompose_answer,
)
from bitmod.interfaces.database import AnswerCacheRecord


class TestCacheEvidence:
    """Verify CacheEvidence dataclass creation and field defaults."""

    def test_basic_creation(self):
        ev = CacheEvidence(layer="exact", confidence=0.95, answer_text="Answer here.")
        assert ev.layer == "exact"
        assert ev.confidence == 0.95
        assert ev.answer_text == "Answer here."

    def test_defaults(self):
        ev = CacheEvidence(layer="semantic", confidence=0.8, answer_text="text")
        assert ev.record_id is None
        assert ev.similarity == 0.0
        assert ev.is_partial is False
        assert ev.sub_query == ""
        assert ev.metadata == {}

    def test_all_fields(self):
        ev = CacheEvidence(
            layer="composable",
            confidence=0.6,
            answer_text="partial",
            record_id="rec-1",
            similarity=0.88,
            is_partial=True,
            sub_query="sub q",
            metadata={"source": "test"},
        )
        assert ev.record_id == "rec-1"
        assert ev.similarity == 0.88
        assert ev.is_partial is True
        assert ev.sub_query == "sub q"
        assert ev.metadata == {"source": "test"}


class TestPipelineEvidence:
    """Verify evidence accumulation with Bayesian confidence stacking."""

    def test_empty_pipeline(self):
        pe = PipelineEvidence()
        assert pe.total_confidence == 0.0
        assert pe.decision == "GENERATE"
        assert pe.evidences == []

    def test_single_evidence(self):
        """Single evidence at 0.85 -> total confidence = 0.85."""
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=0.85, answer_text="a"))
        assert pe.total_confidence == pytest.approx(0.85)

    def test_combining_is_damped_because_the_layers_are_not_independent(self):
        """Noisy-OR treats agreement between layers as separate evidence.

        It is not. Semantic and fuzzy similarity are computed from the same two
        strings, so most of what combining adds is one signal counted twice.
        Measured against labelled pairs, claimed minus observed was +0.011 where
        a single layer contributed, +0.144 at two and +0.386 at three — the
        error appears only where the assumption is used.

        The gain over the strongest single piece of evidence is therefore damped
        rather than taken whole. The raw product remains the ceiling.
        """
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=0.85, answer_text="a"))
        pe.add(CacheEvidence(layer="semantic", confidence=0.50, answer_text="b"))

        undamped = 1.0 - (0.15 * 0.50)
        damping = _get_config().accumulation_damping
        assert pe.total_confidence == pytest.approx(0.85 + (undamped - 0.85) * damping)
        assert 0.85 <= pe.total_confidence < undamped, "combining must add something, but less than noisy-OR claims"

    def test_triple_stacking_damps_further_from_the_best_single_piece(self):
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=0.80, answer_text="a"))
        pe.add(CacheEvidence(layer="semantic", confidence=0.60, answer_text="b"))
        pe.add(CacheEvidence(layer="fuzzy", confidence=0.40, answer_text="c"))

        undamped = 1.0 - (0.20 * 0.40 * 0.60)
        damping = _get_config().accumulation_damping
        assert pe.total_confidence == pytest.approx(0.80 + (undamped - 0.80) * damping)

    def test_a_single_layer_is_untouched(self):
        """Nothing was combined, so there is nothing to correct.

        Measured at +0.011 claimed against observed, i.e. already calibrated.
        An exact match still means certainty.
        """
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=1.0, answer_text="a"))
        assert pe.total_confidence == pytest.approx(1.0)

        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="semantic", confidence=0.73, answer_text="a"))
        assert pe.total_confidence == pytest.approx(0.73)

    def test_zero_confidence_no_effect(self):
        """Evidence with 0.0 confidence does not change total."""
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=0.70, answer_text="a"))
        pe.add(CacheEvidence(layer="semantic", confidence=0.0, answer_text="b"))
        assert pe.total_confidence == pytest.approx(0.70)

    def test_perfect_confidence(self):
        """Evidence at 1.0 drives total to 1.0 regardless of others."""
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=1.0, answer_text="a"))
        pe.add(CacheEvidence(layer="semantic", confidence=0.50, answer_text="b"))
        assert pe.total_confidence == pytest.approx(1.0)


class TestBestSingleAnswer:
    """Verify best_single_answer returns highest-confidence non-partial evidence."""

    def test_returns_highest_non_partial(self):
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="fuzzy", confidence=0.60, answer_text="low"))
        pe.add(CacheEvidence(layer="exact", confidence=0.95, answer_text="high"))
        pe.add(CacheEvidence(layer="composable", confidence=0.99, answer_text="partial", is_partial=True))
        best = pe.best_single_answer()
        assert best is not None
        assert best.answer_text == "high"
        assert best.confidence == 0.95

    def test_returns_none_when_all_partial(self):
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="composable", confidence=0.80, answer_text="p1", is_partial=True))
        pe.add(CacheEvidence(layer="composable", confidence=0.90, answer_text="p2", is_partial=True))
        assert pe.best_single_answer() is None

    def test_returns_none_when_empty(self):
        pe = PipelineEvidence()
        assert pe.best_single_answer() is None


class TestContextForLlm:
    """Verify context_for_llm assembles all evidence sorted by confidence."""

    def test_assembles_all_evidence(self):
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="fuzzy", confidence=0.40, answer_text="Fuzzy result."))
        pe.add(CacheEvidence(layer="exact", confidence=0.95, answer_text="Exact result."))
        ctx = pe.context_for_llm()
        # Higher confidence first
        assert ctx.index("exact") < ctx.index("fuzzy")
        assert "[exact:0.95]" in ctx
        assert "[fuzzy:0.40]" in ctx
        assert "---" in ctx

    def test_includes_sub_query_label(self):
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="composable", confidence=0.70, answer_text="Answer.",
                             sub_query="privacy in CA"))
        ctx = pe.context_for_llm()
        assert "(re: privacy in CA)" in ctx

    def test_skips_empty_answer_text(self):
        pe = PipelineEvidence()
        pe.add(CacheEvidence(layer="exact", confidence=0.90, answer_text=""))
        pe.add(CacheEvidence(layer="fuzzy", confidence=0.50, answer_text="Has content."))
        ctx = pe.context_for_llm()
        assert "exact" not in ctx
        assert "Has content." in ctx


class TestSimilarityToConfidence:
    """Verify the non-linear similarity-to-confidence mapping curves."""

    def test_semantic_confidence_is_a_probability_not_a_hand_drawn_curve(self):
        """The mapping is fitted against labelled pairs, so pin its shape, not its points.

        These asserted the piecewise curve written in the first commit — 0.92
        maps to 0.85, below 0.75 maps to 0.0 — which was never checked against
        data. Its slope inverted: flattest between 0.92 and 0.98, exactly where
        serve decisions are made, so a lone semantic match needed cosine 0.980
        to serve at all.

        Asserting the fitted constants here would just move the unchecked
        numbers into the test. What must hold is that it is monotone, bounded,
        and never claims certainty — the labels do not support certainty, since
        even at cosine 1.0 some pairs are not the same question.
        """
        curve = [_similarity_to_confidence(c / 100, "semantic") for c in range(50, 101)]
        assert curve == sorted(curve), "confidence must not fall as similarity rises"
        assert all(0.0 <= c <= 1.0 for c in curve)
        assert curve[-1] < 1.0, "no similarity should mean certainty"

        # Shape alone does not constrain enough. A curve of 0.9 x cosine is
        # monotone, bounded and never reaches 1.0, yet scores a barely-related
        # question at 0.450 where the fitted curve gives 0.009. These two bands
        # are what the task requires of any curve, wide enough to survive a
        # refit and tight enough that such a curve fails.
        assert _similarity_to_confidence(0.50, "semantic") < 0.10, (
            "a question this dissimilar is not the same question"
        )
        assert _similarity_to_confidence(0.95, "semantic") > 0.60, (
            "a near-identical question must score high enough to serve when a second layer agrees"
        )

    def test_semantic_confidence_is_not_zero_below_the_search_threshold(self):
        """A hard zero is a claim of certainty in the other direction.

        The old curve returned exactly 0.0 below cosine 0.75. Measured, 8.7% of
        the queries it scored that way were genuine duplicates, which is why its
        held-out log loss was 1.87 against the fitted curve's 0.51.
        """
        assert _similarity_to_confidence(0.70, "semantic") > 0.0
        assert _similarity_to_confidence(0.70, "semantic") < _similarity_to_confidence(0.85, "semantic")

    def test_the_hand_drawn_curve_is_still_reachable(self):
        """Calibration is a property of the embedder, so it can be turned off."""
        from bitmod.cache_engine import configure
        from bitmod.config import CacheConfig

        original = _get_config()
        try:
            configure(CacheConfig(calibrated_confidence=False))
            assert _similarity_to_confidence(0.92, "semantic") == pytest.approx(0.85)
            assert _similarity_to_confidence(0.70, "semantic") == 0.0
        finally:
            configure(original)

    def test_fuzzy_high(self):
        """>=0.95 maps to 0.80."""
        assert _similarity_to_confidence(0.95, "fuzzy") == pytest.approx(0.80)
        assert _similarity_to_confidence(0.99, "fuzzy") == pytest.approx(0.80)

    def test_fuzzy_moderate(self):
        """0.90 maps to 0.50."""
        assert _similarity_to_confidence(0.90, "fuzzy") == pytest.approx(0.50)

    def test_fuzzy_low(self):
        """Below 0.85 returns 0.15."""
        assert _similarity_to_confidence(0.80, "fuzzy") == pytest.approx(0.15)

    def test_unknown_layer_passthrough(self):
        """Unknown layer returns raw similarity."""
        assert _similarity_to_confidence(0.77, "unknown") == pytest.approx(0.77)


class TestSemanticMatch:
    """Verify SemanticMatch dataclass."""

    def test_creation(self):
        record = AnswerCacheRecord(answer_key="k", answer_text="Answer.")
        sm = SemanticMatch(record=record, similarity=0.93)
        assert sm.record.answer_text == "Answer."
        assert sm.similarity == 0.93


class TestDecomposeAnswer:
    """Verify atomic fact decomposition: splitting, filtering, categorization."""

    def test_splits_sentences(self):
        text = "Python is a programming language. It was created by Guido van Rossum."
        facts = decompose_answer(text)
        assert len(facts) == 2

    def test_filters_short_sentences(self):
        text = "Python is great. It was created by Guido van Rossum in the early 1990s."
        facts = decompose_answer(text)
        # "Python is great." is < 20 chars, should be filtered
        assert len(facts) == 1
        assert "Guido" in facts[0]["fact_text"]

    def test_filters_filler_sentences(self):
        text = (
            "However this leads to many issues in practice. "
            "The regulation requires companies to notify within 72 hours."
        )
        facts = decompose_answer(text)
        fillers = [f for f in facts if f["fact_text"].startswith("However")]
        assert len(fillers) == 0

    def test_filters_questions(self):
        text = "What do you think about this? The rule requires a 30-day notice period."
        facts = decompose_answer(text)
        questions = [f for f in facts if f["fact_text"].endswith("?")]
        assert len(questions) == 0

    def test_categorizes_definition(self):
        text = "Privacy is defined as the right to be left alone without intrusion."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "definition"

    def test_categorizes_rule(self):
        text = "Companies must report breaches within 72 hours of discovery."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "rule"

    def test_categorizes_comparison(self):
        text = "California's law differs significantly from the federal standard."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "comparison"

    def test_categorizes_procedure(self):
        text = "First you submit the application, then wait for the review process."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "procedure"

    def test_categorizes_statistic(self):
        text = "The company generated $5 billion in revenue last fiscal year."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "statistic"

    def test_categorizes_general(self):
        text = "The California Consumer Privacy Act was signed into law in 2018."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "general"

    def test_extracts_entity(self):
        text = "The European Union enacted the General Data Protection Regulation."
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["entity"] != ""

    def test_empty_input(self):
        assert decompose_answer("") == []

    def test_multiple_filler_patterns(self):
        text = (
            "Additionally there are other considerations here. "
            "I hope this helps you understand the regulations better. "
            "Let me know if you have any further questions about this. "
            "The penalty for non-compliance is $10 million per violation."
        )
        facts = decompose_answer(text)
        assert len(facts) == 1
        assert facts[0]["category"] == "statistic"
