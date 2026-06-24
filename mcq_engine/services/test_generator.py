"""
mcq_engine.services.test_generator
====================================
Public API
----------
    generate_test(topic_id, question_count, experience_level) -> List[Question]

Algorithm
---------
Phase 1 – Difficulty budget
    Compute how many easy / medium / hard questions to draw from the pool
    based on the candidate's experience level:

        FRESHER   : Easy 80%, Medium 20%, Hard  0%
        JUNIOR    : Easy 60%, Medium 20%, Hard 20%
        MID_LEVEL : Easy 50%, Medium 30%, Hard 20%
        SENIOR    : Easy 40%, Medium 30%, Hard 30%

    Rounding: floor each bucket, assign remainder to the largest bucket
    (easy) so that sum(budget.values()) == question_count always.

Phase 2 – Subtopic coverage (guarantee breadth)
    For every subtopic that has at least one question of the required
    difficulty, pick exactly ONE question per subtopic first.
    This ensures no subtopic is skipped when the pool is large enough.

Phase 3 – Random fill
    After coverage, fill the remaining slots for each difficulty bucket
    by randomly sampling from the unused question pool.

Phase 4 – Shuffle & return
    Shuffle the final list so easy / medium / hard are not grouped
    together in the returned order.

Constraints
-----------
* Uses select_related('topic', 'subtopic') to avoid N+1 queries.
* Returns List[Question] (actual Django model instances, not dicts).
* Raises ValueError for invalid inputs and InsufficientQuestionsError
  when the pool cannot satisfy the requested count.
* Zero-sized buckets (e.g. hard for FRESHER) are skipped entirely —
  no pool check and no InsufficientQuestionsError for those buckets.
"""

from __future__ import annotations

import math
import random
from typing import List

from mcq_engine.models import Question, Topic


# ---------------------------------------------------------------------------
# Experience-level difficulty profiles
# ---------------------------------------------------------------------------

DIFFICULTY_PROFILES: dict[str, dict[str, float]] = {
    "FRESHER": {
        "easy":   0.80,
        "medium": 0.20,
        "hard":   0.00,
    },
    "JUNIOR": {
        "easy":   0.60,
        "medium": 0.20,
        "hard":   0.20,
    },
    "MID_LEVEL": {
        "easy":   0.50,
        "medium": 0.30,
        "hard":   0.20,
    },
    "SENIOR": {
        "easy":   0.40,
        "medium": 0.30,
        "hard":   0.30,
    },
}


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class InsufficientQuestionsError(Exception):
    """Raised when the question pool is too small for the requested count."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_difficulty_budget(question_count: int, experience_level: str) -> dict[str, int]:
    """
    Return the number of questions to draw for each difficulty level.

    Uses the DIFFICULTY_PROFILES lookup for the given experience_level.
    Rounding strategy:
        1. Floor each bucket count.
        2. Compute remainder = question_count - sum(floors).
        3. Assign remainder to the bucket with the highest ratio (easy).
    This guarantees sum(budget.values()) == question_count exactly.

    Parameters
    ----------
    question_count : int
        Total number of questions requested.
    experience_level : str
        One of FRESHER / JUNIOR / MID_LEVEL / SENIOR.

    Returns
    -------
    dict mapping difficulty key (str) to count (int).
    """
    profile = DIFFICULTY_PROFILES.get(experience_level, DIFFICULTY_PROFILES["FRESHER"])

    easy_count   = math.floor(question_count * profile["easy"])
    medium_count = math.floor(question_count * profile["medium"])
    hard_count   = math.floor(question_count * profile["hard"])

    # Assign rounding remainder to the largest bucket (easy).
    remainder = question_count - (easy_count + medium_count + hard_count)
    easy_count += remainder

    return {
        Question.Difficulty.EASY:   easy_count,
        Question.Difficulty.MEDIUM: medium_count,
        Question.Difficulty.HARD:   hard_count,
    }


def _fetch_pool(topic_id: int) -> dict[str, list[Question]]:
    """
    Fetch all questions for the topic, grouped by difficulty.

    A single DB query with select_related is used to avoid N+1 issues.
    """
    qs = (
        Question.objects
        .filter(topic_id=topic_id)
        .select_related("topic", "subtopic")
    )

    pool: dict[str, list[Question]] = {
        Question.Difficulty.EASY:   [],
        Question.Difficulty.MEDIUM: [],
        Question.Difficulty.HARD:   [],
    }
    for q in qs:
        if q.difficulty in pool:
            pool[q.difficulty].append(q)

    return pool


def _select_questions(
    candidates: list[Question],
    needed: int,
) -> tuple[list[Question], list[Question]]:
    """
    Phase 2 + Phase 3 combined for a single difficulty bucket.

    Returns:
        selected  – the chosen Question instances (len == needed)
        remaining – unused candidates (for debugging / future use)

    Strategy:
        1. Coverage pass: pick one question per subtopic (shuffled so the
           selection is random when multiple questions exist per subtopic).
        2. Fill pass: randomly sample from leftover questions until `needed`
           is reached.

    Raises:
        InsufficientQuestionsError if len(candidates) < needed.
    """
    if len(candidates) < needed:
        raise InsufficientQuestionsError(
            f"Need {needed} questions but only {len(candidates)} available."
        )

    # Shuffle so coverage picks a random representative per subtopic.
    shuffled = candidates[:]
    random.shuffle(shuffled)

    # --- Phase 2: one-per-subtopic coverage ---
    seen_subtopics: set[int] = set()
    coverage: list[Question] = []
    leftover: list[Question] = []

    for q in shuffled:
        sid = q.subtopic_id
        if sid not in seen_subtopics:
            seen_subtopics.add(sid)
            coverage.append(q)
        else:
            leftover.append(q)

    # If coverage already exceeds budget, trim it randomly.
    if len(coverage) >= needed:
        random.shuffle(coverage)
        selected  = coverage[:needed]
        remaining = coverage[needed:] + leftover
        return selected, remaining

    # --- Phase 3: random fill ---
    still_needed = needed - len(coverage)
    random.shuffle(leftover)
    fill      = leftover[:still_needed]
    remaining = leftover[still_needed:]

    selected = coverage + fill
    return selected, remaining


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_test(topic_id: int, question_count: int, experience_level: str) -> List[Question]:
    """
    Generate a randomised test for the given topic and experience level.

    Parameters
    ----------
    topic_id : int
        Primary key of the Topic to draw questions from.
    question_count : int
        Total number of questions to include in the test.
        Must be a positive integer.
    experience_level : str
        Candidate experience level. One of:
        FRESHER / JUNIOR / MID_LEVEL / SENIOR.
        Controls the easy / medium / hard distribution.

    Returns
    -------
    List[Question]
        A shuffled list of Question model instances with topic and subtopic
        pre-fetched (no additional DB hits needed to access related objects).

    Raises
    ------
    ValueError
        If topic_id or question_count are invalid.
    Topic.DoesNotExist
        If no Topic with the given pk exists.
    InsufficientQuestionsError
        If any non-zero difficulty bucket has fewer questions than needed.
        Zero-sized buckets (e.g. hard for FRESHER) are skipped silently.

    Example
    -------
        from mcq_engine.services.test_generator import generate_test

        questions = generate_test(topic_id=1, question_count=10, experience_level="FRESHER")
        # Returns 8 easy + 2 medium, 0 hard
        for q in questions:
            print(q.difficulty, q.question[:60])
    """
    # --- Input validation ---
    if not isinstance(topic_id, int) or topic_id <= 0:
        raise ValueError(f"topic_id must be a positive integer, got {topic_id!r}.")
    if not isinstance(question_count, int) or question_count <= 0:
        raise ValueError(f"question_count must be a positive integer, got {question_count!r}.")

    # Verify the topic exists (raises Topic.DoesNotExist if not).
    topic_obj = Topic.objects.get(pk=topic_id)

    print("=" * 50)
    print("GENERATE TEST CALLED")
    print("TOPIC:", topic_obj.name)
    print("QUESTION COUNT:", question_count)
    print("EXPERIENCE LEVEL:", experience_level)
    print("=" * 50)

    # --- Build difficulty budget ---
    budget = _compute_difficulty_budget(question_count, experience_level)

    print("BUDGET:", budget)

    # --- Fetch entire question pool in one query ---
    pool = _fetch_pool(topic_id)

    # --- Select questions per difficulty bucket ---
    final_questions: list[Question] = []

    for difficulty, needed in budget.items():
        # Skip zero-sized buckets (e.g. hard=0 for FRESHER) — no error raised.
        if needed == 0:
            continue
        candidates = pool[difficulty]
        try:
            selected, _ = _select_questions(candidates, needed)
        except InsufficientQuestionsError as exc:
            raise InsufficientQuestionsError(
                f"[{difficulty.upper()}] {exc} "
                f"Consider reducing question_count or adding more questions."
            ) from exc
        final_questions.extend(selected)

    # --- Shuffle so difficulties are not clustered together ---
    random.shuffle(final_questions)

    print("QUESTIONS GENERATED:", len(final_questions))
    return final_questions
