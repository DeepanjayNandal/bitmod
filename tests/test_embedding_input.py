"""Both sides of a cosine comparison must be preprocessed identically.

Callers pass raw text and CacheEmbedder applies the transform, so no call site
can choose one preprocessing for what it stores and another for what it looks
up. Pre-normalising before an embed call defeats that, which is what these
checks look for.

The invariant was arrived at by measurement, and the first attempt got it
backwards. The hypothesis was that a cache key wants aggressive collapsing
while an embedding wants the sentence intact — so the two were split and the
embedding side was fed full text. Recall rose eleven points and false positives
went from 13 to 72, because every question shares grammatical scaffolding and
passing it through raises *everything's* similarity. AUC fell from 0.862 to
0.783. Whether to strip is an empirical property of the embedder, configured in
CacheConfig.embedding_normalisation; that both sides must agree is not
negotiable.

The atomic-fact layer is what the invariant was learned from. It embedded a
key-normalised question against facts stored as raw sentences. Over 25
question/fact pairs the mismatch cost 0.20 of median similarity — 0.472 against
0.676 symmetric — which put every fact below the layer's threshold and made a
working layer look dead.

A source check rather than a behavioural one, because the failure has no
symptom: mismatched paths still return answers, still pass every test, and
simply retrieve less. Nothing raises and no counter moves. A test of the two
paths that exist today would not catch a third added later, and a grep near the
embed call misses `embed(norm_query)` where the variable was assigned four
hundred lines earlier — which is how a real site was missed while writing this.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SEARCH_ROOTS = (REPO_ROOT / "core", REPO_ROOT / "services")

KEY_NORMALISER = "normalize_for_key"
EMBED_METHODS = {"embed", "embed_batch"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _is_key_normalise_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == KEY_NORMALISER
    ) or (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == KEY_NORMALISER
    )


def _names_bound_to_key_normalisation(tree: ast.AST) -> set[str]:
    """Variables assigned the output of normalize_for_key, anywhere in the file.

    Deliberately file-scoped rather than per-function. It over-approximates —
    a name reused for something else in another function would be flagged — and
    that is the safe direction for a check whose failure mode is silent.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_key_normalise_call(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _is_key_normalise_call(node.value) and isinstance(node.target, ast.Name):
                bound.add(node.target.id)
    return bound


def _embedding_calls(tree: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in EMBED_METHODS and node.args:
            calls.append(node)
    return calls


def _violations(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:  # pragma: no cover — not this test's business
        return []

    bound = _names_bound_to_key_normalisation(tree)
    found = []
    for call in _embedding_calls(tree):
        first = call.args[0]
        if _is_key_normalise_call(first):
            found.append(f"{path.relative_to(REPO_ROOT)}:{call.lineno} embeds {KEY_NORMALISER}(...) directly")
        elif isinstance(first, ast.Name) and first.id in bound:
            found.append(
                f"{path.relative_to(REPO_ROOT)}:{call.lineno} embeds {first.id!r}, "
                f"which is assigned from {KEY_NORMALISER}()"
            )
    return found


def test_no_embedding_call_receives_key_normalised_text():
    violations: list[str] = []
    for path in _python_files():
        violations.extend(_violations(path))

    assert not violations, "key-normalised text reaching an embedding model:\n  " + "\n  ".join(violations)


def test_the_check_detects_both_shapes(tmp_path):
    """The guard has to fail on the thing it guards, or it guards nothing.

    Covers the direct call and the assigned-variable form. The second is the
    one that matters: it is invisible to a grep for the function name near the
    embed call, and it is how a real site was missed.
    """
    direct = tmp_path / "direct.py"
    direct.write_text("def f(embedder, q):\n    return embedder.embed(normalize_for_key(q))\n")

    indirect = tmp_path / "indirect.py"
    indirect.write_text(
        "def f(embedder, q):\n"
        "    norm = normalize_for_key(q)\n"
        "    other = 1\n"
        "    del other\n"
        "    return embedder.embed(norm)\n"
    )

    for path, shape in ((direct, "direct call"), (indirect, "assigned variable")):
        tree = ast.parse(path.read_text())
        bound = _names_bound_to_key_normalisation(tree)
        calls = _embedding_calls(tree)
        assert calls, f"{shape}: no embedding call found"
        first = calls[0].args[0]
        caught = _is_key_normalise_call(first) or (isinstance(first, ast.Name) and first.id in bound)
        assert caught, f"{shape}: the check failed to flag it"


def test_raw_text_embedding_is_allowed():
    """Document search embeds the query as written, and should keep doing so.

    The rule is not "always call normalize_for_embedding" — it is that key text
    must not be embedded. tool_layer searches document embeddings built from
    natural prose, so passing the raw query is correct there.
    """
    source = "def f(embedder, query):\n    return embedder.embed(query)\n"
    tree = ast.parse(source)
    bound = _names_bound_to_key_normalisation(tree)
    call = _embedding_calls(tree)[0]
    first = call.args[0]
    assert not _is_key_normalise_call(first)
    assert not (isinstance(first, ast.Name) and first.id in bound)


def test_cache_embedder_applies_one_preprocessing_to_every_side():
    """Symmetry by construction, not by every caller remembering.

    The fact layer's defect was that a question and the facts it was compared
    against went through different preprocessing. Naming discipline did not
    prevent it and a test of the two known paths would not have caught a third.
    CacheEmbedder owns the transform, so both sides of any comparison get the
    same one whatever the caller passes.
    """
    pytest.importorskip("bitmod.cache_engine")
    from bitmod.cache_engine import CacheEmbedder, normalize_for_key

    seen: list[str] = []

    class _Spy:
        def embed(self, text):
            seen.append(text)
            return [0.0]

        def dimensions(self):
            return 1

    embedder = CacheEmbedder(_Spy())
    question = "What did Roth discuss with Eddie Van Halen?"
    fact = "David Lee Roth called Eddie Van Halen to discuss the tracks."

    embedder.embed(question)
    embedder.embed(fact)

    assert seen == [normalize_for_key(question), normalize_for_key(fact)], (
        "the two sides were not preprocessed identically"
    )
    assert seen[0] != question, "raw text reached the provider — preprocessing was skipped"


def test_proxy_wraps_any_embedder_assigned_to_it():
    """Assignment after construction must not escape the wrapper.

    Tests and benchmarks set proxy._embedder directly. Wrapping only in
    __init__ would leave those paths embedding raw text into a store built from
    normalised text, which is the asymmetry this prevents and which produces no
    error — only worse recall.
    """
    pytest.importorskip("bitmod.proxy")
    from bitmod.cache_engine import CacheEmbedder
    from bitmod.proxy import BitmodProxy

    class _Raw:
        def embed(self, text):
            return [0.0]

    proxy = BitmodProxy.__new__(BitmodProxy)
    proxy._embedder = _Raw()
    assert isinstance(proxy._embedder, CacheEmbedder), "a directly assigned embedder was not wrapped"

    already = CacheEmbedder(_Raw())
    proxy._embedder = already
    assert proxy._embedder is already, "an already-wrapped embedder was double-wrapped"

    proxy._embedder = None
    assert proxy._embedder is None
