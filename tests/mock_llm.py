"""A deterministic LLM stand-in, shared by tests and both benchmark runners.

The two benchmark runners must differ only in transport — one drives the
pipeline in-process, the other goes over HTTP. If they also differed in how
generation behaves, a disagreement between their numbers could not be
attributed to either. Both therefore produce the same canned completion for the
same input, from the one definition below.

`MockLLM` is the in-process form; `tests/benchmark/stub_llm_server.py` serves
the same answers over an OpenAI-compatible HTTP endpoint.
"""

from __future__ import annotations

from bitmod.interfaces.llm import LLMProvider, LLMResponse

MOCK_MODEL = "mock-model"
STREAM_WORDS = ["Hello", " from", " mock", " LLM"]

# Fixed rather than measured. Nothing here calls a tokenizer, so these are
# placeholders that keep the shape of a usage block; the benchmark reports token
# counts as estimates and does not present them as measurements.
MOCK_INPUT_TOKENS = 10
MOCK_OUTPUT_TOKENS = 20


# Question -> answer, loaded from the benchmark corpus. Empty for ordinary test
# use, where the placeholder below is all anything needs.
#
# The placeholder is not adequate for the benchmark. "Mock answer to: <q>" is
# about 40 characters with no sentence terminator, and atomic-fact extraction
# needs an answer of at least fact_min_answer_length (100) whose sentences clear
# a 30-character floor. Against the placeholder it stored nothing, ever, so the
# fact layer searched an empty table and could never contribute — the layer read
# as dead when it was only ever being starved.
_ANSWER_BOOK: dict[str, str] = {}


def _key(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def load_answer_book(pairs: dict[str, str]) -> None:
    """Install real question/answer pairs for the stub to return."""
    _ANSWER_BOOK.clear()
    _ANSWER_BOOK.update({_key(q): a for q, a in pairs.items() if q and a})


def answer_book_size() -> int:
    return len(_ANSWER_BOOK)


def canned_answer(user_text: str) -> str:
    """The single definition of what a stubbed generation returns.

    Returns the corpus answer when the question is one the book knows, so both
    runners generate identical text for identical input. Falls back to the
    placeholder otherwise, which is what the unit tests rely on.
    """
    known = _ANSWER_BOOK.get(_key(user_text))
    if known:
        return known
    return f"Mock answer to: {user_text}"


def last_user_text(messages) -> str:
    """Extract the most recent user message from LLMMessage objects or dicts."""
    for message in reversed(list(messages)):
        role = getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        if role == "user":
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content", "")
            return content or ""
    return ""


class MockLLM(LLMProvider):
    """In-process provider returning `canned_answer`. Counts its own calls."""

    def __init__(self):
        self.call_count = 0
        self.last_messages = None

    async def generate(self, messages, model="", tools=None, temperature=0.0, max_tokens=4096):
        self.call_count += 1
        self.last_messages = messages
        return LLMResponse(
            content=canned_answer(last_user_text(messages)),
            model=MOCK_MODEL,
            usage={"input_tokens": MOCK_INPUT_TOKENS, "output_tokens": MOCK_OUTPUT_TOKENS},
        )

    async def stream(self, messages, model="", temperature=0.0, max_tokens=4096):
        self.call_count += 1
        self.last_messages = messages
        for word in STREAM_WORDS:
            yield word
