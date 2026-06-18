"""
mcq_engine.services.ai_analysis
=================================
Public API
----------
    generate_ai_analysis(test) -> dict

Orchestrates the full pipeline:
    MCQTest  →  analytics summary  →  LLM prompt  →  Groq  →  validated dict

This module NEVER:
  * modifies any Django model or database record
  * renders templates or returns HttpResponse objects
  * duplicates Groq client initialisation — it reuses the same pattern
    already established in ``resume_analyzer.ai_analyzer`` and
    ``interviews.ai_generator``

Architecture
------------
    generate_ai_analysis(test)
        │
        ├─ _generate_prompt(test)        validates + builds prompt via Phase 6.1 / 6.2
        ├─ _call_groq(prompt)            sends prompt → Groq, returns raw content str
        ├─ _extract_json(content)        strips markdown fences, locates JSON object
        └─ _validate_response(data)      type-checks every required field

Custom exceptions
-----------------
    AIAnalysisError      – base for all failures raised by this module
    AIValidationError    – subclass raised when the AI response schema is wrong
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from groq import (
    APIError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)

from mcq_engine.models import MCQTest
from mcq_engine.services.analysis import build_test_summary
from mcq_engine.services.prompt_builder import build_analysis_prompt

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class AIAnalysisError(Exception):
    """Raised when AI analysis cannot be completed for any reason."""


class AIValidationError(AIAnalysisError):
    """Raised when the AI response does not match the required schema."""


# ---------------------------------------------------------------------------
# Required response schema
# ---------------------------------------------------------------------------

# Maps field name → expected Python type
_REQUIRED_FIELDS: dict[str, type] = {
    "performance_summary":   str,
    "strengths":             list,
    "weaknesses":            list,
    "knowledge_gaps":        list,
    "revision_priority":     list,
    "study_strategy":        str,
    "estimated_revision_time": str,
    "motivation":            str,
}

# Groq model shared with the rest of the project
_GROQ_MODEL = "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_groq_client() -> Groq:
    """
    Return an initialised Groq client using the project-wide ``GROQ_API_KEY``.

    Follows the same guard pattern as ``interviews.ai_generator.get_groq_client``.

    Raises
    ------
    AIAnalysisError
        If the environment variable is absent or empty.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise AIAnalysisError("AI service configuration missing (GROQ_API_KEY not set).")
    return Groq(api_key=api_key)


def _generate_prompt(test: MCQTest) -> tuple[str, dict]:
    """
    Validate the test, compute the analytics summary and build the LLM prompt.

    Parameters
    ----------
    test : MCQTest
        Must be COMPLETED.

    Returns
    -------
    (prompt_str, summary_dict)

    Raises
    ------
    ValueError
        Propagated from ``build_test_summary`` when the test is not
        COMPLETED or has no questions.
    """
    # build_test_summary already enforces COMPLETED status + non-empty questions
    summary = build_test_summary(test)
    prompt  = build_analysis_prompt(summary)
    return prompt, summary


def _call_groq(prompt: str) -> str:
    """
    Send ``prompt`` to Groq and return the raw content string.

    Follows the same call pattern as:
        - ``resume_analyzer.ai_analyzer.analyze_resume``
        - ``interviews.ai_generator.generate_interview_questions``

    Raises
    ------
    AIAnalysisError
        For any Groq API failure (auth, rate-limit, timeout, generic error)
        or an empty / missing response.
    """
    client = _get_groq_client()

    try:
        response = client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=30,
        )
    except AuthenticationError as exc:
        raise AIAnalysisError("AI service authentication failed. Check GROQ_API_KEY.") from exc
    except RateLimitError as exc:
        raise AIAnalysisError("AI service is currently busy. Please try again in a moment.") from exc
    except APITimeoutError as exc:
        raise AIAnalysisError("AI analysis timed out. Please try again.") from exc
    except APIError as exc:
        raise AIAnalysisError(f"AI service error: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected error calling Groq")
        raise AIAnalysisError("Unexpected error communicating with AI service.") from exc

    # ── Guard against empty / malformed Groq response ────────────────────
    if not response:
        raise AIAnalysisError("No response received from AI service.")
    if not response.choices:
        raise AIAnalysisError("AI service returned an empty choices list.")

    message = response.choices[0].message
    if not message or not message.content:
        raise AIAnalysisError("AI service returned a blank message.")

    return message.content.strip()


def _extract_json(content: str) -> dict[str, Any]:
    """
    Strip markdown code fences if present, then locate and parse the JSON
    object in ``content``.

    Uses the same fence-stripping + brace-finding strategy as
    ``interviews.ai_generator.generate_interview_questions``.

    Raises
    ------
    AIAnalysisError
        If no JSON object can be located or the content is not valid JSON.
    """
    # Strip markdown fences (```json … ``` or ``` … ```)
    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()

    # Locate the outermost JSON object
    start = content.find("{")
    end   = content.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise AIAnalysisError(
            "AI response does not contain a valid JSON object."
        )

    json_str = content[start : end + 1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise AIAnalysisError(
            f"AI returned malformed JSON: {exc}"
        ) from exc


def _validate_response(data: dict[str, Any]) -> dict[str, Any]:
    """
    Verify that ``data`` contains every required field with the correct type.

    Raises
    ------
    AIValidationError
        On the first field that is missing or has the wrong type.

    Returns
    -------
    dict
        The validated ``data`` dictionary (unchanged).
    """
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in data:
            raise AIValidationError(
                f"AI response is missing required field: '{field}'."
            )
        if not isinstance(data[field], expected_type):
            raise AIValidationError(
                f"Field '{field}' must be {expected_type.__name__}, "
                f"got {type(data[field]).__name__}."
            )

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ai_analysis(test: MCQTest) -> dict[str, Any]:
    """
    Generate a personalised AI performance analysis for a completed MCQTest.

    Parameters
    ----------
    test : MCQTest
        A fully completed MCQTest instance.

    Returns
    -------
    dict
        A validated, pure-Python dictionary with the following keys:

        ``performance_summary`` (str)
        ``strengths``           (list[str])
        ``weaknesses``          (list[str])
        ``knowledge_gaps``      (list[str])
        ``revision_priority``   (list[str])
        ``study_strategy``      (str)
        ``estimated_revision_time`` (str)
        ``motivation``          (str)

    Raises
    ------
    ValueError
        If the test is not COMPLETED or has no questions
        (propagated from ``build_test_summary``).
    AIAnalysisError
        For any Groq connectivity / response failure.
    AIValidationError
        If the AI response does not match the required schema.
    """
    # Step 1 + 2 + 3: validate test, compute analytics, build prompt
    prompt, summary = _generate_prompt(test)

    logger.info(
        "mcq_ai_analysis_start test_id=%s topic=%s",
        test.pk,
        summary.get("topic"),
    )

    # Step 4: call Groq
    raw_content = _call_groq(prompt)

    # Step 5 + 6: extract JSON
    data = _extract_json(raw_content)

    # Step 7: validate schema
    validated = _validate_response(data)

    logger.info(
        "mcq_ai_analysis_complete test_id=%s",
        test.pk,
    )

    # Step 8: return pure Python dict (no model instances, no DB writes)
    return validated
