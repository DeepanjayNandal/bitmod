"""A cached answer is refused when the two questions name different things.

Embedding similarity says whether two sentences are alike. It does not say
whether they are about the same subject, and a cache needs the second. Two
questions from one template with a name swapped score as near-identical because
they are, so no threshold reaches them — the confidence is high and correct.

Every case below was served from cache by the real pipeline against 500
labelled pairs.
"""

from __future__ import annotations

from bitmod.entity_guard import conflicts, extract


class TestRealServesThatWereWrong:
    """Taken from the measured runs, not invented."""

    def test_different_company_same_template(self):
        assert conflicts(
            "What universities does Sigma-Aldrich recruit new grads from?",
            "What universities does Sigma Designs recruit new grads from?",
        )
        assert conflicts(
            "What universities does Chart Industries recruit new grads from?",
            "What universities does Powell Industries recruit new grads from?",
        )

    def test_different_country_same_template(self):
        assert conflicts(
            "Why is saltwater taffy candy imported in Austria?",
            "Why is Saltwater taffy candy imported in China?",
        )

    def test_the_case_the_product_pitch_opens_with(self):
        """"Refund policy for US customers" against "EU customers".

        Named in the README as the thing the cache handles, with no mechanism
        for it until now: layer 4 scores the two as similar because they are.
        """
        assert conflicts(
            "What is the refund policy for US customers?",
            "What is the refund policy for EU customers?",
        )


class TestServesThatWereRight:
    """A veto that fires on these costs recall for nothing."""

    def test_one_sided_detail_is_not_a_conflict(self):
        """Extra specificity is not disagreement about the subject."""
        assert not conflicts(
            "Which is the best gaming laptop under 60,000 INR?",
            "Which is the best gaming laptop under 60000 INR?",
        )

    def test_a_shorter_name_for_the_same_thing(self):
        assert not conflicts(
            "Does Donald Trump have any chance of winning the election?",
            "Does Trump have a chance at winning presidency?",
        )

    def test_roman_numerals_are_the_same_number(self):
        assert not conflicts(
            "Is World War 3 more imminent than expected?",
            "How imminent is world war III?",
        )

    def test_capitalisation_alone_does_not_name_something(self):
        assert not conflicts(
            "How can I learn to speak English fluently?",
            "HOw do I speak Fluent English?",
        )

    def test_a_question_with_no_entities_is_never_vetoed(self):
        assert not conflicts("How do I stop procrastinating?", "How can I stop procrastinating?")


class TestExtraction:
    def test_sentence_openers_are_not_entities(self):
        """Otherwise every question contributes its first word and all conflict."""
        assert extract("What is the refund policy?") == set()
        assert "how" not in extract("How do I reset my password?")

    def test_acronyms_and_numbers_survive(self):
        assert "us" in extract("What is the US refund policy?")
        assert "500" in extract("Why were 500 rupee notes banned?")

    def test_containment_does_not_confuse_similar_names(self):
        """Token containment, not substring — Austria is not inside Australia."""
        assert conflicts("Is it cold in Austria?", "Is it cold in Australia?")
