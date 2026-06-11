"""
mcq_engine.services.test_generator
====================================
Public API
----------
    generate_test(topic_id, question_count) -> List[Question]

Algorithm
---------
Phase 1 – Difficulty budget
    Compute how many easy / medium / hard questions to draw from the pool:
        easy   = 40 % of question_count  (rounded)
        medium = 30 % of question_count  (rounded)
        hard   = remaining slots         (avoids rounding drift)

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
"""

from __future__ import annotations

import math
import random
from typing import List

from mcq_engine.models import Question, Topic


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class InsufficientQuestionsError(Exception):
    """Raised when the question pool is too small for the requested count."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_difficulty_budget(question_count: int) -> dict[str, int]:
    """
    Return the number of questions to draw for each difficulty level.

    Distribution: 40 % easy, 30 % medium, 30 % hard.
    The hard count absorbs any rounding remainder so the total is exact.
    """
    easy_count   = round(question_count * 0.40)
    medium_count = round(question_count * 0.30)
    hard_count   = question_count - easy_count - medium_count  # absorb drift
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

def generate_test(topic_id: int, question_count: int) -> List[Question]:
    """
    Generate a randomised test for the given topic.

    Parameters
    ----------
    topic_id : int
        Primary key of the Topic to draw questions from.
    question_count : int
        Total number of questions to include in the test.
        Must be a positive integer.

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
        If any difficulty bucket has fewer questions than the computed budget.

    Example
    -------
        from mcq_engine.services.test_generator import generate_test

        questions = generate_test(topic_id=1, question_count=20)
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
    print("=" * 50)

    # --- Build difficulty budget ---
    budget = _compute_difficulty_budget(question_count)

    # --- Fetch entire question pool in one query ---
    pool = _fetch_pool(topic_id)

    # --- Select questions per difficulty bucket ---
    final_questions: list[Question] = []

    for difficulty, needed in budget.items():
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
