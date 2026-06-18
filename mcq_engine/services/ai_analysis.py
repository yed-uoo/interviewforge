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
        ├─ _extract_json(content)        sanitises + locates + parses JSON object
        │      tolerates: markdown fences, trailing commas, smart quotes,
        │                 raw newlines inside strings, extra whitespace
        └─ _validate_response(data)      type-checks every required field

Custom exceptions
-----------------
    AIAnalysisError      – base for all failures raised by this module
    AIValidationError    – subclass raised when the AI response schema is wrong

Retry behaviour
---------------
    If _extract_json() or _validate_response() fails on the first Groq call,
    generate_ai_analysis() automatically retries _call_groq() once before
    raising the error to the caller.
"""

from __future__ import annotations

import json
import logging
import os
import re
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
        raise AIAnalysisError(
            "API failure: AI service authentication failed. Check GROQ_API_KEY."
        ) from exc
    except RateLimitError as exc:
        raise AIAnalysisError(
            "API failure: AI service is currently busy. Please try again in a moment."
        ) from exc
    except APITimeoutError as exc:
        raise AIAnalysisError(
            "API failure: AI analysis timed out. Please try again."
        ) from exc
    except APIError as exc:
        raise AIAnalysisError(f"API failure: AI service error: {exc}") from exc
    except Exception as exc:
        logger.exception("Unexpected error calling Groq")
        raise AIAnalysisError(
            "API failure: Unexpected error communicating with AI service."
        ) from exc

    # ── Guard against empty / malformed Groq response ────────────────────
    if not response:
        raise AIAnalysisError("API failure: No response received from AI service.")
    if not response.choices:
        raise AIAnalysisError("API failure: AI service returned an empty choices list.")

    message = response.choices[0].message
    if not message or not message.content:
        raise AIAnalysisError("API failure: AI service returned a blank message.")

    return message.content.strip()


def _sanitise_json_string(raw: str) -> str:
    """
    Apply a series of tolerant transformations to clean up common LLM
    JSON formatting issues before parsing.

    Transformations (in order):
    1. Strip markdown code fences (```json … ``` or ``` … ```)
    2. Replace curly/smart quotes with straight ASCII quotes
    3. Remove control characters that are illegal in JSON string values
       (specifically bare CR, LF, TAB — i.e. the bytes 0x00-0x1F except
       those already escaped as \\n, \\t, \\r).
    4. Remove trailing commas before } or ] (invalid JSON but common in LLMs)
    5. Strip surrounding whitespace
    """
    s = raw

    # 1. Strip markdown code fences (any position, not just start-of-string)
    s = re.sub(r"```(?:json)?", "", s)
    s = s.replace("```", "")

    # 2. Normalise smart / curly quotes to ASCII equivalents
    s = s.replace("\u2018", "'").replace("\u2019", "'")  # left/right single quotes
    s = s.replace("\u201c", '"').replace("\u201d", '"')  # left/right double quotes
    s = s.replace("\u201e", '"').replace("\u201f", '"')  # double low-9 / reversed

    # 3. Replace raw (unescaped) control characters inside JSON strings.
    #    We process character-by-character only inside string literals to
    #    avoid mangling whitespace that is part of the JSON structure itself.
    #    Strategy: outside strings, control chars are structural (fine to keep
    #    \n, \t for readability). Inside strings we replace bare \n/\r/\t
    #    with their JSON escape sequences.
    result = []
    inside_string = False
    escape_next   = False
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            result.append(ch)
            escape_next = True
            continue
        if ch == '"':
            inside_string = not inside_string
            result.append(ch)
            continue
        if inside_string:
            # Replace bare control characters with JSON escape sequences
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            elif ord(ch) < 0x20:
                # Other ASCII control chars — just skip them
                pass
            else:
                result.append(ch)
        else:
            result.append(ch)
    s = "".join(result)

    # 4. Remove trailing commas before closing braces / brackets
    #    (e.g. {"key": "value",} or ["a", "b",])
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # 5. Strip surrounding whitespace
    s = s.strip()

    return s


def _extract_json(content: str) -> dict[str, Any]:
    """
    Locate and parse the JSON object in ``content``, tolerating common LLM
    formatting issues.

    Processing steps
    ----------------
    1. Log the full raw response at DEBUG level.
    2. Sanitise the content with ``_sanitise_json_string``.
    3. Find the outermost ``{...}`` block.
    4. Attempt ``json.loads``.

    Raises
    ------
    AIAnalysisError
        – "JSON extraction failure: …"  — if no JSON object is found.
        – "JSON parsing failure: …"     — if ``json.loads`` fails after
                                          sanitisation.
    """
    # 1. Log raw response for debugging
    logger.debug("AI raw response (length=%d):\n%s", len(content), content)

    # 2. Sanitise
    sanitised = _sanitise_json_string(content)

    # 3. Locate outermost JSON object
    start = sanitised.find("{")
    end   = sanitised.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise AIAnalysisError(
            "JSON extraction failure: AI response does not contain a valid JSON object."
        )

    json_str = sanitised[start : end + 1]

    # 4. Parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise AIAnalysisError(
            f"JSON parsing failure: AI returned malformed JSON after sanitisation: {exc}"
        ) from exc


def _validate_response(data: dict[str, Any]) -> dict[str, Any]:
    """
    Verify that ``data`` contains every required field with the correct type.

    Raises
    ------
    AIValidationError
        "Schema validation failure: …" on the first field that is missing
        or has the wrong type.

    Returns
    -------
    dict
        The validated ``data`` dictionary (unchanged).
    """
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in data:
            raise AIValidationError(
                f"Schema validation failure: AI response is missing required field: '{field}'."
            )
        if not isinstance(data[field], expected_type):
            raise AIValidationError(
                f"Schema validation failure: field '{field}' must be "
                f"{expected_type.__name__}, got {type(data[field]).__name__}."
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
        For any Groq connectivity / response failure, JSON extraction failure,
        or JSON parsing failure.
    AIValidationError
        If the AI response does not match the required schema.

    Retry behaviour
    ---------------
    If JSON extraction or schema validation fails on the first attempt,
    the Groq call is retried once.  If the retry also fails, the exception
    from the retry is raised.
    """
    # Step 1 + 2 + 3: validate test, compute analytics, build prompt
    prompt, summary = _generate_prompt(test)

    logger.info(
        "mcq_ai_analysis_start test_id=%s topic=%s",
        test.pk,
        summary.get("topic"),
    )

    def _attempt(attempt_number: int) -> dict[str, Any]:
        """Single attempt: call Groq → extract JSON → validate schema."""
        logger.debug("mcq_ai_analysis attempt=%d test_id=%s", attempt_number, test.pk)
        raw_content = _call_groq(prompt)
        data        = _extract_json(raw_content)
        return _validate_response(data)

    # First attempt
    try:
        validated = _attempt(1)
    except (AIAnalysisError, AIValidationError) as first_exc:
        # Only retry on extraction/validation failures, not on API auth errors
        if "API failure: AI service authentication failed" in str(first_exc):
            raise

        logger.warning(
            "mcq_ai_analysis first attempt failed (test_id=%s): %s — retrying once",
            test.pk,
            first_exc,
        )
        # Retry once
        validated = _attempt(2)   # propagates if it also fails

    logger.info("mcq_ai_analysis_complete test_id=%s", test.pk)

    # Return pure Python dict (no model instances, no DB writes)
    return validated
