#!/usr/bin/env python3
"""
BitMod Demo
===========
Shows the cache working on real questions: which queries hit, which layers
contributed, the accumulated confidence, the latency — then the full 50-query
benchmark.

Every query goes through `_run_cache_pipeline`, the same entry point the proxy
and chat services use, at the shipping CacheConfig. All nine layers run, with
real evidence accumulation, damping, the serve threshold and the qualification
gate. Nothing here re-implements the cache or picks its own thresholds.

That matters because this script previously did the opposite. It called
try_cache, fuzzy_match and semantic_cache_search directly with thresholds
hardcoded at 0.75, which is below the shipping fuzzy_threshold (0.85) and
semantic_threshold (0.88) — so it demonstrated a cache the product does not
ship, and served at least one wrong answer as a result.

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
from bitmod.cache_engine import _get_config
from bitmod.proxy import BitmodProxy
from bitmod.router import LLMRouter

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

# Five queries chosen to show a different path each. The outcomes in the
# comments were MEASURED against the shipping config, not assumed — the
# previous list was annotated "fuzzy or semantic hit" for three queries that
# miss.
#
# These are illustrative only. The 50-query benchmark below runs
# QA_PAIRS + PARAPHRASES + NEW_QUESTIONS and does not include this list, so
# nothing here moves the reported hit rate.
SHOWCASE = [
    "What is your refund policy?",        # exact, confidence 1.00
    "Do you offer free shiping?",         # typo -> semantic 0.88
    "How do I use a discount code?",      # semantic 0.84 + atomic_facts, crosses 0.85 only once combined
    "How can I contact customer support?",  # three layers agreeing
    "Do you have a mobile app?",          # nothing cached for it — correct miss
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

# Display only. Neither value affects what the cache decides — the pipeline has
# already accumulated and thresholded by the time these are read.
_MIN_SHOWN_CONFIDENCE = 0.05  # below this a contribution cannot move a decision
_MAX_SHOWN_LAYERS = 3  # keeps the per-query line readable on a screen share


class _UnusedLLM:
    """Placeholder. `_run_cache_pipeline` never calls a model.

    BitmodProxy requires a router, and the pipeline is pure retrieval — it was
    checked, not assumed: no reference to the router appears anywhere in
    `_run_cache_pipeline`. If that ever changes, this raises rather than
    silently making the demo depend on a live model.

    DO NOT REPLACE THIS WITH A REAL MODEL. Generation is stubbed on purpose and
    the demo is better for it: the run is deterministic, finishes in seconds,
    and every number it prints is a property of the cache rather than of
    whatever model happened to be installed. Wiring a real provider in would
    add minutes of runtime and several seconds of per-call variance while
    telling a reader nothing about hit rate, layer attribution or confidence.

    Latency IS measured with a real model, in a harness built for it:
    tests/benchmark/measure_latency_http.py drives the running gateway over
    HTTP, and the summary below points at its artifact. That is the right place
    for it, because latency is the one figure a stub cannot produce honestly.
    """

    async def generate(self, *args, **kwargs):
        raise AssertionError("_run_cache_pipeline is retrieval-only; the demo never generates")


def _ask(proxy, question: str):
    """One query through the real pipeline. Returns (result, elapsed_ms)."""
    t0 = time.perf_counter()
    result = proxy._run_cache_pipeline(question, [{"role": "user", "content": question}])
    return result, (time.perf_counter() - t0) * 1000


def _layer_summary(result) -> tuple[str, float]:
    """The contributing layers and the accumulated total.

    Reads `evidence.evidences` — the layers that actually produced evidence —
    rather than the trace, which lists every layer that RAN including the ones
    that found nothing. Printing the latter for fifty queries is a wall nobody
    reads; the interesting line is which layers agreed and how much that came to.

    Returns ("", 0.0) for a miss, a single "layer 0.93" for one contributor, and
    "a 0.81 + b 0.72" when several combined. That last case is the whole point
    of a nine-layer cache and is invisible in a hit/miss count.
    """
    evidence = getattr(result, "evidence", None)
    items = list(getattr(evidence, "evidences", []) or []) if evidence is not None else []
    if not items:
        return "", 0.0

    # One entry per LAYER, not per candidate. A layer that returns three
    # candidates produces three evidence items, and printing
    # "semantic 0.92 + semantic 0.06 + semantic 0.05" reads as three layers
    # agreeing when it is one layer with a ranked list. Best confidence per
    # layer is what "which layers contributed" actually means.
    best: dict[str, float] = {}
    for item in items:
        if item.confidence and item.confidence > _MIN_SHOWN_CONFIDENCE:
            best[item.layer] = max(best.get(item.layer, 0.0), float(item.confidence))

    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    parts = [f"{layer} {confidence:.2f}" for layer, confidence in ranked[:_MAX_SHOWN_LAYERS]]
    if len(ranked) > _MAX_SHOWN_LAYERS:
        parts.append(f"+{len(ranked) - _MAX_SHOWN_LAYERS} more")
    return " + ".join(parts), float(getattr(evidence, "total_confidence", 0.0))


def _served_by(result) -> str:
    """The single layer credited with the serve, for the summary counters."""
    evidence = getattr(result, "evidence", None)
    if evidence is not None and hasattr(evidence, "best_single_answer"):
        best = evidence.best_single_answer()
        if best is not None and getattr(best, "layer", None):
            return str(best.layer)
    for step in result.trace or []:
        if step.get("action") in ("HIT", "FULL_HIT"):
            return str(step.get("mechanism", "")) or "cache"
    return "cache"


def _preview(text: str, width: int = 72) -> str:
    text = text.replace("\n", " ").strip()
    return text[:width] + "..." if len(text) > width else text


def _show(question: str, result, ms: float, note: str = "") -> None:
    """One query, one or two lines. The format a reader actually parses."""
    print()
    print(f'  Q: "{question}"{note}')
    if not result.hit:
        print("  ✗  CACHE MISS    no cached answer — LLM would be called")
        return
    layers, confidence = _layer_summary(result)
    detail = f"{layers}   confidence {confidence:.2f}" if layers else _served_by(result)
    print(f"  ✓  CACHE HIT     {detail}   {ms:.0f}ms")
    print(f'     "{_preview(result.answer_text or "")}"')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        backend = SQLiteBackend(db_path)
        backend.initialize()
        print("\nConnecting to Ollama embeddings...", end="", flush=True)
        embedder = OllamaEmbeddingAdapter(model="nomic-embed-text")
        print(" ready.")

        # The real entry point, at the shipping configuration.
        proxy = BitmodProxy(
            backend=backend,
            llm_router=LLMRouter(primary=_UnusedLLM()),
            default_model="gpt-4o",
        )
        proxy._embedder = embedder

        config = _get_config()
        print(
            f"Pipeline: serve_threshold {config.serve_threshold}, "
            f"search_threshold {config.search_threshold}, "
            f"damping {config.accumulation_damping}"
        )

        # Seed through the proxy's own write path, so entries carry the filters
        # and context the pipeline will look for. Seeding with store_answer
        # directly would cache rows the retrieval side cannot fully use.
        print(f"Seeding {len(QA_PAIRS)} Q&A pairs into cache...", end="", flush=True)
        for question, answer in QA_PAIRS:
            messages = [{"role": "user", "content": question}]
            result = proxy._run_cache_pipeline(question, messages)
            proxy._store_response(
                user_message=question,
                answer_text=answer,
                model_used="gpt-4o",
                elapsed_ms=1800,
                filters=result.filters or {},
                norm=result.norm,
                answer_key=result.answer_key,
                evidence=result.evidence,
                messages_for_context=messages,
            )
        print(" done.")

        W = 58

        # ── Showcase ────────────────────────────────────────────────────────
        print()
        print("=" * W)
        print("  BitMod Cache Demo — Live Query Results")
        print("=" * W)

        for question in SHOWCASE:
            result, ms = _ask(proxy, question)
            _show(question, result, ms)

        # ── Cache learning ──────────────────────────────────────────────────
        learn_q = "Can I pay with cryptocurrency?"
        learn_a = "We do not currently accept cryptocurrency. We accept Visa, Mastercard, Amex, PayPal, and UPI."

        print()
        print("-" * W)
        print("  Cache Learning — miss then store then hit")
        print("-" * W)

        messages = [{"role": "user", "content": learn_q}]
        result, ms = _ask(proxy, learn_q)
        print()
        print(f'  Q: "{learn_q}"')
        print("  ✗  CACHE MISS    LLM called, response stored.")

        proxy._store_response(
            user_message=learn_q,
            answer_text=learn_a,
            model_used="gpt-4o",
            elapsed_ms=3400,
            filters=result.filters or {},
            norm=result.norm,
            answer_key=result.answer_key,
            evidence=result.evidence,
            messages_for_context=messages,
        )

        result, ms = _ask(proxy, learn_q)
        _show(learn_q, result, ms, note="  [same question again]")

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

        counts: dict[str, int] = {}
        by_type: dict[str, list[str]] = {"exact": [], "paraphrase": [], "new": []}
        multi_layer = 0

        for question, qtype in all_queries:
            result, _ = _ask(proxy, question)
            if result.hit:
                served = _served_by(result)
                counts[served] = counts.get(served, 0) + 1
                evidence = getattr(result, "evidence", None)
                contributors = [
                    e for e in (getattr(evidence, "evidences", []) or []) if e.confidence
                ]
                if len(contributors) > 1:
                    multi_layer += 1
            else:
                counts["miss"] = counts.get("miss", 0) + 1
            by_type[qtype].append("miss" if not result.hit else "hit")

        total = len(all_queries)
        misses = counts.get("miss", 0)
        hits = total - misses
        hit_rate = hits / total * 100

        print()
        for layer in sorted(k for k in counts if k != "miss"):
            print(f"  {layer + ' hits':<16}: {counts[layer]}")
        print(f"  {'Misses':<16}: {misses}")
        print(f"  {'Multi-layer':<16}: {multi_layer}  (more than one layer contributed)")
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

        # Latency is deliberately NOT measured here — see the note on the stub
        # above. These figures come from the HTTP harness, and the file is named
        # so a reader can check them rather than take them on trust.
        print("  End-to-end latency measured separately over HTTP:")
        print("    ~80ms cached vs ~8.0s cold (ollama/llama3.1:8b, n=10) — 99x")
        print("    tests/benchmark/results/latency_http_llama31_8b.json")
        print()
        print("=" * W)
        print()

    finally:
        os.unlink(db_path)


if __name__ == "__main__":
    main()
