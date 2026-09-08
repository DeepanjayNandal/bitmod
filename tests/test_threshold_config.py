"""Threshold configuration — the env vars have to reach the pipeline.

The pipeline passed threshold literals to callees that would otherwise have read
them from config. Those callees consult config only in an `if threshold is None`
branch, so an explicit literal does not override the default loudly — it
disables the environment variable with no error and no log line.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Config actually reaches the pipeline
# ---------------------------------------------------------------------------


def _config_with(**env) -> object:
    """Build a CacheConfig in a subprocess-free way, with env applied."""
    from bitmod.config import CacheConfig

    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return CacheConfig()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.parametrize(
    "env_var,attr,value,expected",
    [
        ("BITMOD_CACHE_SEMANTIC_THRESHOLD", "semantic_threshold", "0.55", 0.55),
        ("BITMOD_CACHE_FUZZY_THRESHOLD", "fuzzy_threshold", "0.60", 0.60),
        ("BITMOD_CACHE_SEARCH_THRESHOLD", "search_threshold", "0.42", 0.42),
        ("BITMOD_CACHE_SERVE_THRESHOLD", "serve_threshold", "0.70", 0.70),
        ("BITMOD_CACHE_FUZZY_PREFIX_LENGTH", "fuzzy_prefix_length", "4", 4),
        ("BITMOD_CACHE_FACT_MIN_SIMILARITY", "fact_min_similarity", "0.66", 0.66),
        ("BITMOD_CACHE_LINK_HOP2_DISCOUNT", "link_hop2_discount", "0.11", 0.11),
    ],
)
def test_env_var_reaches_config(env_var, attr, value, expected):
    cfg = _config_with(**{env_var: value})
    assert getattr(cfg, attr) == expected


def test_no_hardcoded_thresholds_remain_in_the_pipeline():
    """REGRESSION GUARD — literals silently shadow config.

    The callees read config only in an `if threshold is None` branch, so passing
    an explicit literal does not override the default loudly; it disables the
    environment variable with no error and no log line. Reading either file
    alone makes it look correct.
    """
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "core" / "bitmod" / "proxy" / "base.py"
    ).read_text()
    for literal in ("threshold=0.75", "similarity_threshold=0.85", "serve_threshold = 0.95"):
        assert literal not in source, f"{literal!r} is hardcoded again — it shadows the env var silently"
