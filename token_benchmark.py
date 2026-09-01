#!/usr/bin/env python3
"""
BitMod Token Reduction Benchmark
=================================
Measures actual output token reduction when cached context is injected
into partial-hit LLM calls, using Ollama for real token counts.

For each test query:
  1. Sends it to Ollama with NO context  — records prompt + output tokens (baseline)
  2. Finds the best cached answer via semantic search
  3. Sends it to Ollama WITH context injected — records prompt + output tokens
  4. Computes output token reduction

The prompt format with context exactly mirrors services/chat/app/main.py:1296-1306.

Usage:
    cd bitmod
    pip install -e core/
    python token_benchmark.py
"""

import os
import sys
import tempfile

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))

from bitmod.adapters.db_sqlite import SQLiteBackend
from bitmod.adapters.embed_ollama import OllamaEmbeddingAdapter
from bitmod.cache_engine import compute_answer_key, normalize_query_fuzzy, semantic_cache_search, store_answer

OLLAMA_URL = "http://localhost:11434"
LLM_MODEL = "llama3.2"
EMBED_MODEL = "nomic-embed-text"
SYSTEM_PROMPT = "You are a helpful customer support assistant. Answer concisely and directly."

# ---------------------------------------------------------------------------
# 30 Q&A pairs seeded into cache (same as demo.py)
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
# Partial-match queries: related to cached Q&A but with different vocabulary.
# Goal: trigger semantic search (partial hit path) rather than exact/fuzzy match.
# ---------------------------------------------------------------------------

PARTIAL_QUERIES = [
    "Can I get my money back if I am not satisfied with my purchase?",
    "I want to know where my package is right now",
    "I forgot my login credentials and cannot get into my account",
    "Is there a promotion for free delivery on my order?",
    "I want to stop my monthly membership plan",
    "Which credit and debit cards do you take as payment?",
    "How many days will it take before my purchase arrives?",
    "My parcel got broken during shipping, what should I do?",
    "Do you deliver to other countries outside of this one?",
    "Is there a rewards scheme for regular customers?",
    "How do I enter a voucher code when buying something?",
    "I received my order but one item is missing from the box",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ollama_chat(messages: list[dict]) -> dict:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": LLM_MODEL, "messages": messages, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def build_messages(question: str, cached_context: str | None = None) -> list[dict]:
    """Mirrors the exact prompt format in services/chat/app/main.py:1296-1306."""
    user_content = question
    if cached_context:
        user_content = (
            f"{question}\n\n"
            f"## Prior Cached Knowledge (verified, already served to users)\n"
            f"The following answer was previously generated and cached for a closely related query. "
            f"This information is already verified — DO NOT regenerate or rephrase what is already covered. "
            f"Instead:\n"
            f"1. Extract any directly relevant facts from the cached answer below.\n"
            f"2. Only generate NEW content that addresses the specific question above but is NOT covered below.\n"
            f"3. Reference the cached material naturally (e.g., 'As previously noted...').\n"
            f"4. If the cached answer fully addresses the question, state that concisely.\n\n"
            f"--- CACHED ANSWER START ---\n{cached_context}\n--- CACHED ANSWER END ---"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        backend = SQLiteBackend(db_path)

        print("\nConnecting to Ollama...", end="", flush=True)
        embedder = OllamaEmbeddingAdapter(model=EMBED_MODEL)
        print(" ready.")

        print("\n" + "=" * 62)
        print("  BitMod Token Reduction Benchmark")
        print("=" * 62)

        # Seed cache
        print(f"\nSeeding {len(QA_PAIRS)} Q&A pairs...", end="", flush=True)
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
                    model_used=LLM_MODEL,
                    generation_ms=0,
                    query_embedding=embedding,
                )
        print(" done.")

        print(f"\nRunning {len(PARTIAL_QUERIES)} queries — each called twice (with and without context).")
        print("This takes a few minutes.\n")

        header = f"  {'Query (truncated)':<42} {'Sim':>5}  {'Out↓':>5}  {'In↑':>5}  {'Net':>6}"
        print(header)
        print("  " + "-" * 62)

        rows = []

        with backend.session() as session:
            for query in PARTIAL_QUERIES:
                # Find best cached context
                matches = semantic_cache_search(
                    backend, session, query, filters={},
                    embedder=embedder, threshold=0.55, max_results=1,
                )

                if not matches:
                    print(f"  {query[:41]:<42}   no match — skipped")
                    continue

                cached_context = matches[0].record.answer_text
                similarity = matches[0].similarity

                # Baseline: no context
                r_base = ollama_chat(build_messages(query))
                in_base = r_base.get("prompt_eval_count", 0)
                out_base = r_base.get("eval_count", 0)

                # With context injected
                r_ctx = ollama_chat(build_messages(query, cached_context))
                in_ctx = r_ctx.get("prompt_eval_count", 0)
                out_ctx = r_ctx.get("eval_count", 0)

                out_reduction = ((out_base - out_ctx) / out_base * 100) if out_base else 0
                in_increase = in_ctx - in_base
                net_change = in_increase - (out_base - out_ctx)

                rows.append({
                    "query": query,
                    "similarity": similarity,
                    "in_base": in_base,
                    "out_base": out_base,
                    "in_ctx": in_ctx,
                    "out_ctx": out_ctx,
                    "out_reduction_pct": out_reduction,
                    "in_increase": in_increase,
                    "net_change": net_change,
                })

                print(
                    f"  {query[:41]:<42} {similarity:.2f}  "
                    f"{out_reduction:>+.0f}%  {in_increase:>+4}  {net_change:>+5}"
                )

        if not rows:
            print("\nNo results — check Ollama is running and models are pulled.")
            return

        # Aggregates
        avg_out_base = sum(r["out_base"] for r in rows) / len(rows)
        avg_out_ctx = sum(r["out_ctx"] for r in rows) / len(rows)
        avg_out_red = sum(r["out_reduction_pct"] for r in rows) / len(rows)
        avg_in_base = sum(r["in_base"] for r in rows) / len(rows)
        avg_in_ctx = sum(r["in_ctx"] for r in rows) / len(rows)
        avg_in_inc = sum(r["in_increase"] for r in rows) / len(rows)
        avg_net = sum(r["net_change"] for r in rows) / len(rows)
        min_red = min(r["out_reduction_pct"] for r in rows)
        max_red = max(r["out_reduction_pct"] for r in rows)

        print()
        print("=" * 62)
        print("  SUMMARY")
        print("=" * 62)
        print(f"  Queries measured          : {len(rows)}")
        print()
        print(f"  Output tokens (baseline)  : {avg_out_base:.0f} avg")
        print(f"  Output tokens (w/ context): {avg_out_ctx:.0f} avg")
        print(f"  Output token reduction    : {avg_out_red:.0f}% avg  (range {min_red:.0f}%–{max_red:.0f}%)")
        print()
        print(f"  Input tokens (baseline)   : {avg_in_base:.0f} avg")
        print(f"  Input tokens (w/ context) : {avg_in_ctx:.0f} avg")
        print(f"  Input token increase      : +{avg_in_inc:.0f} avg (context added to prompt)")
        print()
        print(f"  Net token change per call : {avg_net:+.0f} avg tokens")
        print()
        print("  Output token reduction range usable in README:")
        r_lo = max(0, int(min_red // 5) * 5)
        r_hi = min(100, int((max_red + 4) // 5) * 5)
        print(f"    '{r_lo}%–{r_hi}%' (rounded to nearest 5)")
        print("=" * 62)
        print()

    finally:
        os.unlink(db_path)


if __name__ == "__main__":
    main()
