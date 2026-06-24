"""
mcq_engine.services.analysis
==============================
Public API
----------
    build_test_summary(test) -> dict

Converts a completed MCQTest instance into a structured, JSON-serialisable
performance dictionary.  No database writes, no AI calls, no side effects.

Return structure
----------------
{
    "test_id":             int,
    "user_id":             int,
    "topic":               str,
    "generated_at":        str  (ISO-8601),

    "total_questions":     int,
    "score":               int,
    "correct":             int,
    "wrong":               int,
    "unknown":             int,
    "percentage":          float,
    "unknown_percentage":  float,
    "completion_rate":     float,

    "difficulty_breakdown": {
        "easy":   {"correct": int, "wrong": int, "unknown": int, "total": int, "accuracy": float},
        "medium": {...},
        "hard":   {...},
    },

    "subtopic_breakdown": {
        "<subtopic_name>": {"correct": int, "wrong": int, "unknown": int, "total": int, "accuracy": float},
        ...
    },

    "strengths":           [str, ...],   # subtopics with accuracy >= 80 %, sorted desc
    "weak_areas":          [str, ...],   # subtopics with accuracy <  50 %, sorted asc
    "critical_weak_areas": [str, ...],   # subtopics with accuracy == 0 OR all-unknown
}

Performance
-----------
* Uses select_related / prefetch_related to load all related data in a
  small, fixed number of queries — never N+1.
* All computation is done in Python; zero additional DB hits after load.

Constraints
-----------
* Does NOT modify any model.
* Does NOT call AI.
* Does NOT render templates.
* Raises ValueError for invalid/incomplete input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcq_engine.models import MCQTest, MCQTestQuestion


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _empty_bucket() -> dict[str, int]:
    """Return a fresh counter bucket for one difficulty or subtopic."""
    return {"correct": 0, "wrong": 0, "unknown": 0, "total": 0}


def _compute_accuracy(correct: int, total: int) -> float:
    """Return accuracy as a percentage, rounded to 2 d.p."""
    if total == 0:
        return 0.0
    return round((correct / total) * 100, 2)


def _finalize_bucket(bucket: dict[str, int]) -> dict[str, Any]:
    """Add the 'accuracy' key to a counter bucket and return it."""
    bucket["accuracy"] = _compute_accuracy(bucket["correct"], bucket["total"])
    return bucket


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_test_summary(test: MCQTest) -> dict[str, Any]:
    """
    Build a structured performance summary for a completed MCQTest.

    Parameters
    ----------
    test : MCQTest
        A fully completed MCQTest instance.

    Returns
    -------
    dict
        A pure-Python, JSON-serialisable performance dictionary (see module
        docstring for the exact shape).

    Raises
    ------
    ValueError
        If the test has no questions, or if the test status is not COMPLETED.
    """
    # --- Guard: only operate on completed tests ---
    if test.status != MCQTest.Status.COMPLETED:
        raise ValueError(
            f"build_test_summary requires a COMPLETED test, "
            f"but test {test.pk} has status '{test.status}'."
        )

    # -----------------------------------------------------------------------
    # Load all MCQTestQuestion rows together with their related Question
    # and MCQAnswer in as few queries as possible.
    #
    # Query plan:
    #   1. MCQTestQuestion  (+ select_related Question → Topic, Subtopic)
    #   2. MCQAnswer        (prefetched via test.answers.all())
    # -----------------------------------------------------------------------
    test_questions = list(
        MCQTestQuestion.objects
        .filter(test=test)
        .select_related(
            "question",
            "question__subtopic",
            "question__topic",
        )
        .order_by("order")
    )

    total_questions = len(test_questions)

    if total_questions == 0:
        raise ValueError(
            f"build_test_summary requires at least one question, "
            f"but test {test.pk} has none."
        )

    # Build a lookup: question_id -> MCQAnswer for O(1) access below.
    # A single queryset fetches every answer for this test.
    from mcq_engine.models import MCQAnswer  # local import avoids circular risk

    answers_qs = MCQAnswer.objects.filter(test=test).select_related("question")
    answer_map: dict[int, MCQAnswer] = {
        ans.question_id: ans for ans in answers_qs
    }

    # -----------------------------------------------------------------------
    # Accumulators
    # -----------------------------------------------------------------------
    correct = 0
    wrong   = 0
    unknown = 0

    DIFFICULTIES = ("easy", "medium", "hard")
    difficulty_breakdown: dict[str, dict] = {d: _empty_bucket() for d in DIFFICULTIES}
    subtopic_breakdown:   dict[str, dict] = {}

    # -----------------------------------------------------------------------
    # Single pass over test questions
    # -----------------------------------------------------------------------
    for tq in test_questions:
        q      = tq.question
        answer = answer_map.get(q.pk)  # may be None if somehow unanswered

        difficulty_key = q.difficulty.lower()  # "easy" / "medium" / "hard"
        subtopic_name  = q.subtopic.name

        # Initialise subtopic bucket on first encounter
        if subtopic_name not in subtopic_breakdown:
            subtopic_breakdown[subtopic_name] = _empty_bucket()

        # Increment totals
        difficulty_breakdown[difficulty_key]["total"] += 1
        subtopic_breakdown[subtopic_name]["total"]    += 1

        # Classify the answer
        if answer is None or answer.selected_option == "X":
            # Treat missing answers (edge case) the same as "I Don't Know"
            unknown += 1
            difficulty_breakdown[difficulty_key]["unknown"] += 1
            subtopic_breakdown[subtopic_name]["unknown"]    += 1
        elif answer.is_correct:
            correct += 1
            difficulty_breakdown[difficulty_key]["correct"] += 1
            subtopic_breakdown[subtopic_name]["correct"]    += 1
        else:
            wrong += 1
            difficulty_breakdown[difficulty_key]["wrong"] += 1
            subtopic_breakdown[subtopic_name]["wrong"]    += 1

    # -----------------------------------------------------------------------
    # Derived metrics
    # -----------------------------------------------------------------------
    percentage = round((correct / total_questions) * 100, 2)

    unknown_percentage = round((unknown / total_questions) * 100, 2)

    attempted      = correct + wrong
    completion_rate = round((attempted / total_questions) * 100, 2)

    # Finalise difficulty buckets (add accuracy key)
    for key in DIFFICULTIES:
        _finalize_bucket(difficulty_breakdown[key])

    # Finalise subtopic buckets
    for key in subtopic_breakdown:
        _finalize_bucket(subtopic_breakdown[key])

    # -----------------------------------------------------------------------
    # Strength / Weak-area / Critical-weak-area detection
    # -----------------------------------------------------------------------
    strengths:           list[str] = []
    weak_areas:          list[str] = []
    critical_weak_areas: list[str] = []

    for subtopic_name, bucket in subtopic_breakdown.items():
        accuracy = bucket["accuracy"]
        total_st = bucket["total"]
        unknown_st = bucket["unknown"]

        if accuracy >= 80.0:
            strengths.append((accuracy, subtopic_name))

        if accuracy < 50.0:
            weak_areas.append((accuracy, subtopic_name))

        # Critical: accuracy == 0 OR every question answered with Option X
        if accuracy == 0.0 or unknown_st == total_st:
            critical_weak_areas.append(subtopic_name)

    # Sort strengths: highest accuracy first
    strengths.sort(key=lambda t: t[0], reverse=True)
    strengths = [name for _, name in strengths]

    # Sort weak areas: lowest accuracy first
    weak_areas.sort(key=lambda t: t[0])
    weak_areas = [name for _, name in weak_areas]

    # -----------------------------------------------------------------------
    # Assemble and return the summary dictionary
    # -----------------------------------------------------------------------
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    return {
        "test_id":    test.pk,
        "user_id":    test.user_id,
        "topic":      test.topic.name,
        "generated_at": generated_at,

        "experience_level": test.experience_level,

        "total_questions":    total_questions,
        "score":              correct,
        "correct":            correct,
        "wrong":              wrong,
        "unknown":            unknown,
        "percentage":         percentage,
        "unknown_percentage": unknown_percentage,
        "completion_rate":    completion_rate,

        "difficulty_breakdown": difficulty_breakdown,
        "subtopic_breakdown":   subtopic_breakdown,

        "strengths":           strengths,
        "weak_areas":          weak_areas,
        "critical_weak_areas": critical_weak_areas,
    }
