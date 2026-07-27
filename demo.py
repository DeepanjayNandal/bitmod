#!/usr/bin/env python3
"""
BitMod Demo
===========
Shows the cache working on real questions: which queries hit, which layer
served them, the answer, the latency — then the full 50-query benchmark.

Usage:
    cd bitmod
    python3 demo.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter
from bitmod.cache_engine import (
    compute_answer_key,
    fuzzy_match,
    normalize_query_fuzzy,
    semantic_cache_search,
    store_answer,
    try_cache,
)

# ---------------------------------------------------------------------------
# 30 customer support Q&A pairs seeded into cache
# ---------------------------------------------------------------------------

QA_PAIRS = [
    ("What is your refund policy?", "You can return any unused item within 30 days for a full refund. Items must be in original packaging."),
    ("How do I track my order?", "Go to My Orders in your account and click Track. You will get real-time updates via email too."),
    ("How do I reset my password?", "Click Forgot Password on the login page. We will send a reset link to your email within 5 minutes."),
    ("Do you offer free shipping?", "Yes, free shipping on all orders over $50. Standard delivery takes 3-5 business days."),
    ("How do I cancel my subscription?", "Go to Account Settings, click Subscriptions, then Cancel. Your access continues until the billing period ends."),
    ("What payment methods do you accept?", "We accept Visa, Mastercard, Amex, PayPal, and UPI. All payments are encrypted and secure."),
    ("How long does delivery take?", "Standard delivery is 3-5 business days. Express delivery is 1-2 business days for an extra charge."),
    ("Can I change my delivery address?", "Yes, you can change the address within 1 hour of placing the order. After that, contact support."),
    ("How do I contact customer support?", "You can reach us by email at support@store.com or live chat Monday to Friday 9am to 6pm."),
    ("Is my payment information safe?", "Yes, we use 256-bit SSL encryption. We never store your full card number on our servers."),
    ("How do I apply a discount code?", "Enter the code in the Promo Code box at checkout and click Apply. The discount shows before payment."),
    ("What happens if my item arrives damaged?", "Take a photo and email it to support within 48 hours. We will send a replacement or full refund immediately."),
    ("Do you ship internationally?", "Yes, we ship to over 50 countries. International delivery takes 7-14 business days."),
    ("How do I update my email address?", "Go to Account Settings and click Edit next to your email. You will need to verify the new address."),
    ("Can I return a sale item?", "Sale items can be returned for store credit only, not a cash refund. The 30-day window still applies."),
    ("What is your privacy policy?", "We never sell your data to third parties. We only use your information to process orders and improve our service."),
    ("How do I delete my account?", "Email support@store.com with your account email and we will delete your account within 7 days."),
    ("Do you have a loyalty program?", "Yes, you earn 1 point per dollar spent. 100 points equals $1 off your next order."),
    ("How do I leave a product review?", "Go to the product page and scroll down to Reviews. You need to have purchased the item to leave a review."),
    ("What if I ordered the wrong size?", "You can exchange within 30 days. Return the item and place a new order, or contact us for an exchange."),
    ("Do you offer gift cards?", "Yes, gift cards are available in amounts from $10 to $500. They never expire and can be used online only."),
    ("How do I unsubscribe from emails?", "Click Unsubscribe at the bottom of any email. It takes up to 48 hours to take effect."),
    ("Can I split payment across two cards?", "No, we only accept one payment method per order. You can use a gift card plus one other method."),
    ("What is express delivery?", "Express delivery arrives in 1-2 business days. It costs $9.99 and is available for most locations."),
    ("How do I check my order status?", "Log into your account and go to My Orders. You will see the current status and estimated delivery date."),
    ("Do you price match?", "Yes, we match any competitor price within 7 days of purchase. Send us the link and we will process the difference."),
    ("What is your warranty policy?", "All products come with a 1-year manufacturer warranty. Extended warranty is available at checkout."),
    ("How do I report a missing item?", "Contact support within 48 hours of delivery with your order number. We will investigate and reship within 24 hours."),
    ("Can I pre-order out of stock items?", "Yes, click Notify Me on the product page and we will email you when it is back in stock."),
    ("How do I refer a friend?", "Go to Account Settings and click Refer a Friend. Share your link and you both get $10 off your next order."),
]

# ---------------------------------------------------------------------------
# Showcase queries — hand-picked to demonstrate each cache layer + a miss
# ---------------------------------------------------------------------------

SHOWCASE = [
    "What is your refund policy?",      # exact hit
    "How do I track my order?",         # exact hit
    "What is the refund policy?",       # fuzzy or semantic hit
    "Is my payment info safe?",         # fuzzy or semantic hit
    "How long does shipping take?",     # fuzzy or semantic hit
    "Do you have a mobile app?",        # miss
    "Can I schedule a delivery time?",  # miss
]

# ---------------------------------------------------------------------------
# Full benchmark queries
# ---------------------------------------------------------------------------

PARAPHRASES = [
    "What is the refund policy?",
    "How can I track my order?",
    "How can I reset my password?",
    "Do you have free shipping?",
    "How can I cancel my subscription?",
    "What payment options do you accept?",
    "How long does shipping take?",
    "Can I update my delivery address?",
    "How can I contact customer support?",
    "Is my payment info safe?",
    "How do I use a discount code?",
    "What happens when my item arrives damaged?",
    "Do you ship to other countries?",
    "How can I update my email address?",
    "Can I return a discounted item?",
]

NEW_QUESTIONS = [
    "Do you have a mobile app?",
    "Can I schedule a delivery time?",
    "Do you offer student discounts?",
    "How do I add items to a wishlist?",
    "What are your business hours?",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lookup(backend, session, question: str, embedder) -> tuple[str, str, float]:
    """Return (hit_type, answer_text, elapsed_ms)."""
    t0 = time.perf_counter()

    result = try_cache(backend, session, question, filters={})
    if result:
        ms = (time.perf_counter() - t0) * 1000
        return "exact", result.answer_text, ms

    fuzzy = fuzzy_match(backend, session, question, filters={}, similarity_threshold=0.75, max_candidates=3)
    if fuzzy:
        ms = (time.perf_counter() - t0) * 1000
        return "fuzzy", fuzzy[0].answer_text, ms

    sem = semantic_cache_search(backend, session, question, filters={}, embedder=embedder, threshold=0.75, max_results=3)
    if sem:
        ms = (time.perf_counter() - t0) * 1000
        label = f"semantic · {sem[0].similarity:.2f} similarity"
        return label, sem[0].record.answer_text, ms

    ms = (time.perf_counter() - t0) * 1000
    return "miss", "", ms


def _preview(text: str, width: int = 72) -> str:
    text = text.replace("\n", " ").strip()
    return text[:width] + "..." if len(text) > width else text


def _hit_type_for_stats(hit_type: str) -> str:
    if hit_type == "exact":
        return "exact_hit"
    if hit_type == "fuzzy":
        return "fuzzy_hit"
    if hit_type == "miss":
        return "miss"
    return "semantic_hit"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        backend = SQLiteBackend(db_path)
        print("\nConnecting to Ollama embeddings...", end="", flush=True)
        embedder = OllamaEmbeddingAdapter(model="nomic-embed-text")
        print(" ready.\n")

        # Seed
        print(f"Seeding {len(QA_PAIRS)} Q&A pairs into cache...", end="", flush=True)
        with backend.session() as session:
            for question, answer in QA_PAIRS:
                embedding = embedder.embed(question)
                store_answer(
                    backend, session,
                    answer_key=compute_answer_key(question),
                    question_raw=question,
                    question_normalized=normalize_query_fuzzy(question),
                    filters={},
                    answer_text=answer,
                    source_sections=[],
                    model_used="gpt-4o",
                    generation_ms=1800,
                    query_embedding=embedding,
                )
        print(" done.")

        W = 58

        # ── Showcase ────────────────────────────────────────────────────────
        print()
        print("=" * W)
        print("  BitMod Cache Demo — Live Query Results")
        print("=" * W)

        with backend.session() as session:
            for question in SHOWCASE:
                hit_type, answer_text, ms = _lookup(backend, session, question, embedder)

                print()
                print(f"  Q: \"{question}\"")
                if hit_type == "miss":
                    print(f"  ✗  CACHE MISS    no cached answer — LLM would be called")
                else:
                    print(f"  ✓  CACHE HIT     {hit_type}    {ms:.0f}ms")
                    print(f"     \"{_preview(answer_text)}\"")

        # ── Cache learning ──────────────────────────────────────────────────
        LEARN_Q = "Can I pay with cryptocurrency?"
        LEARN_A = "We do not currently accept cryptocurrency. We accept Visa, Mastercard, Amex, PayPal, and UPI."

        print()
        print("-" * W)
        print("  Cache Learning — miss then store then hit")
        print("-" * W)

        with backend.session() as session:
            hit_type, _, _ = _lookup(backend, session, LEARN_Q, embedder)
            print()
            print(f"  Q: \"{LEARN_Q}\"")
            print(f"  ✗  CACHE MISS    LLM called, response stored.")

            embedding = embedder.embed(LEARN_Q)
            store_answer(
                backend, session,
                answer_key=compute_answer_key(LEARN_Q),
                question_raw=LEARN_Q,
                question_normalized=normalize_query_fuzzy(LEARN_Q),
                filters={},
                answer_text=LEARN_A,
                source_sections=[],
                model_used="gpt-4o",
                generation_ms=3400,
                query_embedding=embedding,
            )

            hit_type, answer_text, ms = _lookup(backend, session, LEARN_Q, embedder)
            print()
            print(f"  Q: \"{LEARN_Q}\"  [same question again]")
            print(f"  ✓  CACHE HIT     {hit_type}    {ms:.0f}ms")
            print(f"     \"{_preview(answer_text)}\"")

        # ── Full benchmark ───────────────────────────────────────────────────
        print()
        print("-" * W)
        print("  Full benchmark: 50 queries")
        print("-" * W)

        all_queries = (
            [(q, "exact") for q, _ in QA_PAIRS]
            + [(q, "paraphrase") for q in PARAPHRASES]
            + [(q, "new") for q in NEW_QUESTIONS]
        )

        counts = {"exact_hit": 0, "fuzzy_hit": 0, "semantic_hit": 0, "miss": 0}
        by_type: dict[str, list[str]] = {"exact": [], "paraphrase": [], "new": []}

        with backend.session() as session:
            for question, qtype in all_queries:
                hit_type, _, _ = _lookup(backend, session, question, embedder)
                stat = _hit_type_for_stats(hit_type)
                counts[stat] += 1
                by_type[qtype].append(stat)

        total = len(all_queries)
        hits = total - counts["miss"]
        hit_rate = hits / total * 100

        print()
        print(f"  Exact hits    : {counts['exact_hit']}")
        print(f"  Fuzzy hits    : {counts['fuzzy_hit']}")
        print(f"  Semantic hits : {counts['semantic_hit']}")
        print(f"  Misses        : {counts['miss']}")
        print()
        print(f"  ✓ Cache hit rate: {hit_rate:.0f}%")
        print()

        def rate(lst: list[str]) -> str:
            h = sum(1 for r in lst if r != "miss")
            return f"{h}/{len(lst)} ({h / len(lst) * 100:.0f}%)"

        print("  Breakdown by query type:")
        print(f"    Same questions again  : {rate(by_type['exact'])}")
        print(f"    Rephrased questions   : {rate(by_type['paraphrase'])}")
        print(f"    New unseen questions  : {rate(by_type['new'])}  ← correct, should miss")
        print()
        print("=" * W)
        print()

    finally:
        os.unlink(db_path)


if __name__ == "__main__":
    main()
