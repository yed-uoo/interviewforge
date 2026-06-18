"""
mcq_engine.services.analysis_cache
=====================================
Public API
----------
    get_or_generate_analysis(test) -> dict

Cache-aside layer that sits between a caller (view, task, etc.) and the
AI analysis pipeline:

    ┌──────────────────────────────────────┐
    │  get_or_generate_analysis(test)      │
    │                                      │
    │  test.ai_analysis populated?         │
    │      YES  →  return cached dict      │
    │      NO   →  generate_ai_analysis()  │
    │              save to test.ai_analysis│
    │              return fresh dict       │
    └──────────────────────────────────────┘

Rules
-----
* Analysis is generated **at most once per test**.
* A failed generation is NEVER persisted — ``ai_analysis`` remains ``{}``.
* Only ``update_fields=["ai_analysis"]`` is used; no other field is touched.
* No templates, no HTTP, no model creation — pure service logic.
"""

from __future__ import annotations

import logging
from typing import Any

from mcq_engine.models import MCQTest
from mcq_engine.services.ai_analysis import generate_ai_analysis

logger = logging.getLogger(__name__)


def get_or_generate_analysis(test: MCQTest) -> dict[str, Any]:
    """
    Return the cached AI analysis for *test*, generating and persisting it
    on the first call.

    Parameters
    ----------
    test : MCQTest
        Must be a COMPLETED MCQTest instance.

    Returns
    -------
    dict
        The validated AI analysis dictionary (8 required keys).

    Raises
    ------
    ValueError
        If the test is not COMPLETED (propagated from
        ``generate_ai_analysis`` → ``build_test_summary``).
    AIAnalysisError / AIValidationError
        If the Groq call fails or the response is malformed.
        The exception propagates without touching ``test.ai_analysis``.

    Notes
    -----
    ``test.ai_analysis`` defaults to ``{}`` (empty dict).  Any falsy value
    (``{}``, ``None``, ``[]``) is treated as "not yet cached" and triggers
    generation.  This makes the cache robust against accidental resets.
    """
    # ── Guard ────────────────────────────────────────────────────────────
    if test.status != MCQTest.Status.COMPLETED:
        raise ValueError(
            f"get_or_generate_analysis requires a COMPLETED test, "
            f"but test {test.pk} has status '{test.status}'."
        )

    # ── Cache hit ─────────────────────────────────────────────────────────
    if test.ai_analysis:
        logger.info(
            "mcq_analysis_cache_hit test_id=%s",
            test.pk,
        )
        return test.ai_analysis

    # ── Cache miss: generate, persist, return ─────────────────────────────
    logger.info(
        "mcq_analysis_cache_miss test_id=%s — calling AI",
        test.pk,
    )

    # generate_ai_analysis raises on any failure; we let exceptions propagate
    # so that nothing is saved on error.
    analysis = generate_ai_analysis(test)

    # Persist only the new field; leave every other column untouched.
    test.ai_analysis = analysis
    test.save(update_fields=["ai_analysis"])

    logger.info(
        "mcq_analysis_cache_stored test_id=%s",
        test.pk,
    )

    return analysis
