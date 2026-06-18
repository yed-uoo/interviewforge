"""
Tests for mcq_engine.services.analysis.build_test_summary
==========================================================

Coverage
--------
✓ Perfect score
✓ All wrong
✓ All Option X (unknown)
✓ Mixed answers
✓ Multiple difficulties
✓ Multiple subtopics
✓ Strength detection  (accuracy >= 80 %)
✓ Weak area detection (accuracy < 50 %)
✓ Critical weak area  (accuracy == 0 OR all-unknown subtopic)
✓ Unknown percentage
✓ Completion rate
✓ Empty test raises ValueError
✓ In-progress test raises ValueError
"""

import json
from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mcq_engine.models import (
    MCQAnswer,
    MCQTest,
    MCQTestQuestion,
    Question,
    Subtopic,
    Topic,
)
from mcq_engine.services.analysis import build_test_summary

User = get_user_model()


# ---------------------------------------------------------------------------
# Base fixture mixin
# ---------------------------------------------------------------------------

class AnalysisTestBase(TestCase):
    """
    Creates a minimal but reusable fixture:
        user, topic, subtopics (cpu, memory), a helpers for building
        questions, test-question links, and answers.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user  = User.objects.create_user(username="analyst", password="pass")
        cls.topic = Topic.objects.create(name="Operating Systems")

        cls.sub_cpu    = Subtopic.objects.create(topic=cls.topic, name="CPU Scheduling")
        cls.sub_memory = Subtopic.objects.create(topic=cls.topic, name="Memory Management")
        cls.sub_dead   = Subtopic.objects.create(topic=cls.topic, name="Deadlocks")

    # ---- helpers --------------------------------------------------------

    def _make_question(self, subtopic, difficulty=Question.Difficulty.MEDIUM,
                       correct_option="A"):
        return Question.objects.create(
            topic=self.topic,
            subtopic=subtopic,
            difficulty=difficulty,
            question="Placeholder question?",
            option_a="Alpha",
            option_b="Beta",
            option_c="Gamma",
            option_d="Delta",
            correct_option=correct_option,
        )

    def _make_test(self, n_questions, status=MCQTest.Status.COMPLETED,
                   score=0, percentage=0.0):
        test = MCQTest.objects.create(
            user=self.user,
            topic=self.topic,
            total_questions=n_questions,
            score=score,
            percentage=percentage,
            status=status,
            submitted_at=timezone.now() if status == MCQTest.Status.COMPLETED else None,
        )
        return test

    def _link(self, test, question, order):
        return MCQTestQuestion.objects.create(test=test, question=question, order=order)

    def _answer(self, test, question, selected, is_correct):
        return MCQAnswer.objects.create(
            test=test,
            question=question,
            selected_option=selected,
            is_correct=is_correct,
        )


# ===========================================================================
# Test classes
# ===========================================================================


class TestPerfectScore(AnalysisTestBase):
    """All answers correct → 100 % score, zero wrong/unknown."""

    def setUp(self):
        q1 = self._make_question(self.sub_cpu)
        q2 = self._make_question(self.sub_cpu)
        self.test = self._make_test(2, score=2, percentage=100.0)
        self._link(self.test, q1, 1)
        self._link(self.test, q2, 2)
        self._answer(self.test, q1, "A", True)
        self._answer(self.test, q2, "A", True)

    def test_perfect_score_metrics(self):
        s = build_test_summary(self.test)
        self.assertEqual(s["correct"],  2)
        self.assertEqual(s["wrong"],    0)
        self.assertEqual(s["unknown"],  0)
        self.assertEqual(s["score"],    2)
        self.assertAlmostEqual(s["percentage"],      100.0, places=2)
        self.assertAlmostEqual(s["unknown_percentage"], 0.0, places=2)
        self.assertAlmostEqual(s["completion_rate"], 100.0, places=2)

    def test_perfect_score_subtopic_accuracy(self):
        s = build_test_summary(self.test)
        cpu = s["subtopic_breakdown"]["CPU Scheduling"]
        self.assertAlmostEqual(cpu["accuracy"], 100.0, places=2)
        self.assertEqual(cpu["correct"], 2)


class TestAllWrong(AnalysisTestBase):
    """All answers wrong → 0 % score, full wrong count, completion_rate 100 %."""

    def setUp(self):
        q1 = self._make_question(self.sub_memory, correct_option="A")
        q2 = self._make_question(self.sub_memory, correct_option="A")
        self.test = self._make_test(2, score=0, percentage=0.0)
        self._link(self.test, q1, 1)
        self._link(self.test, q2, 2)
        self._answer(self.test, q1, "B", False)  # wrong
        self._answer(self.test, q2, "C", False)  # wrong

    def test_all_wrong_metrics(self):
        s = build_test_summary(self.test)
        self.assertEqual(s["correct"],  0)
        self.assertEqual(s["wrong"],    2)
        self.assertEqual(s["unknown"],  0)
        self.assertAlmostEqual(s["percentage"],      0.0,   places=2)
        self.assertAlmostEqual(s["completion_rate"], 100.0, places=2)

    def test_all_wrong_is_critical(self):
        s = build_test_summary(self.test)
        self.assertIn("Memory Management", s["critical_weak_areas"])

    def test_all_wrong_is_weak(self):
        s = build_test_summary(self.test)
        self.assertIn("Memory Management", s["weak_areas"])


class TestAllUnknown(AnalysisTestBase):
    """All answers Option X → unknown == total, completion_rate == 0 %."""

    def setUp(self):
        q1 = self._make_question(self.sub_dead)
        q2 = self._make_question(self.sub_dead)
        self.test = self._make_test(2, score=0, percentage=0.0)
        self._link(self.test, q1, 1)
        self._link(self.test, q2, 2)
        self._answer(self.test, q1, "X", False)
        self._answer(self.test, q2, "X", False)

    def test_all_unknown_metrics(self):
        s = build_test_summary(self.test)
        self.assertEqual(s["unknown"],  2)
        self.assertEqual(s["correct"],  0)
        self.assertEqual(s["wrong"],    0)
        self.assertAlmostEqual(s["unknown_percentage"], 100.0, places=2)
        self.assertAlmostEqual(s["completion_rate"],      0.0, places=2)

    def test_all_unknown_is_critical(self):
        s = build_test_summary(self.test)
        self.assertIn("Deadlocks", s["critical_weak_areas"])


class TestMixedAnswers(AnalysisTestBase):
    """3 correct, 1 wrong, 1 unknown across 5 questions."""

    def setUp(self):
        self.questions = [self._make_question(self.sub_cpu) for _ in range(5)]
        self.test = self._make_test(5, score=3, percentage=60.0)
        for i, q in enumerate(self.questions, start=1):
            self._link(self.test, q, i)

        self._answer(self.test, self.questions[0], "A", True)
        self._answer(self.test, self.questions[1], "A", True)
        self._answer(self.test, self.questions[2], "A", True)
        self._answer(self.test, self.questions[3], "B", False)
        self._answer(self.test, self.questions[4], "X", False)

    def test_mixed_totals(self):
        s = build_test_summary(self.test)
        self.assertEqual(s["correct"],  3)
        self.assertEqual(s["wrong"],    1)
        self.assertEqual(s["unknown"],  1)
        self.assertEqual(s["total_questions"], 5)

    def test_mixed_percentage(self):
        s = build_test_summary(self.test)
        self.assertAlmostEqual(s["percentage"],          60.0, places=2)
        self.assertAlmostEqual(s["unknown_percentage"],  20.0, places=2)
        self.assertAlmostEqual(s["completion_rate"],     80.0, places=2)


class TestMultipleDifficulties(AnalysisTestBase):
    """One question per difficulty; verify difficulty_breakdown totals."""

    def setUp(self):
        self.q_easy   = self._make_question(self.sub_cpu,    Question.Difficulty.EASY)
        self.q_medium = self._make_question(self.sub_cpu,    Question.Difficulty.MEDIUM)
        self.q_hard   = self._make_question(self.sub_memory, Question.Difficulty.HARD)

        self.test = self._make_test(3, score=2, percentage=66.67)
        self._link(self.test, self.q_easy,   1)
        self._link(self.test, self.q_medium, 2)
        self._link(self.test, self.q_hard,   3)

        self._answer(self.test, self.q_easy,   "A", True)
        self._answer(self.test, self.q_medium, "A", True)
        self._answer(self.test, self.q_hard,   "B", False)

    def test_difficulty_breakdown_totals(self):
        s = build_test_summary(self.test)
        db = s["difficulty_breakdown"]
        self.assertEqual(db["easy"]["total"],   1)
        self.assertEqual(db["medium"]["total"], 1)
        self.assertEqual(db["hard"]["total"],   1)

    def test_difficulty_breakdown_correct(self):
        s = build_test_summary(self.test)
        db = s["difficulty_breakdown"]
        self.assertEqual(db["easy"]["correct"],   1)
        self.assertEqual(db["medium"]["correct"], 1)
        self.assertEqual(db["hard"]["correct"],   0)
        self.assertEqual(db["hard"]["wrong"],     1)

    def test_difficulty_accuracy(self):
        s = build_test_summary(self.test)
        db = s["difficulty_breakdown"]
        self.assertAlmostEqual(db["easy"]["accuracy"],   100.0, places=2)
        self.assertAlmostEqual(db["medium"]["accuracy"], 100.0, places=2)
        self.assertAlmostEqual(db["hard"]["accuracy"],     0.0, places=2)


class TestMultipleSubtopics(AnalysisTestBase):
    """Questions span three subtopics; subtopic_breakdown must have all three."""

    def setUp(self):
        q_cpu  = self._make_question(self.sub_cpu)
        q_mem  = self._make_question(self.sub_memory)
        q_dead = self._make_question(self.sub_dead)

        self.test = self._make_test(3, score=2, percentage=66.67)
        self._link(self.test, q_cpu,  1)
        self._link(self.test, q_mem,  2)
        self._link(self.test, q_dead, 3)

        self._answer(self.test, q_cpu,  "A", True)
        self._answer(self.test, q_mem,  "A", True)
        self._answer(self.test, q_dead, "B", False)

    def test_all_subtopics_present(self):
        s = build_test_summary(self.test)
        sb = s["subtopic_breakdown"]
        self.assertIn("CPU Scheduling",     sb)
        self.assertIn("Memory Management",  sb)
        self.assertIn("Deadlocks",          sb)

    def test_subtopic_individual_accuracy(self):
        s = build_test_summary(self.test)
        sb = s["subtopic_breakdown"]
        self.assertAlmostEqual(sb["CPU Scheduling"]["accuracy"],    100.0, places=2)
        self.assertAlmostEqual(sb["Memory Management"]["accuracy"], 100.0, places=2)
        self.assertAlmostEqual(sb["Deadlocks"]["accuracy"],           0.0, places=2)


class TestStrengthDetection(AnalysisTestBase):
    """
    CPU Scheduling: 4/5 correct → 80 % → strength
    Deadlocks:      1/5 correct → 20 % → NOT a strength
    """

    def setUp(self):
        # 5 CPU questions, 4 correct
        cpu_qs = [self._make_question(self.sub_cpu) for _ in range(5)]
        # 5 Deadlock questions, 1 correct
        dead_qs = [self._make_question(self.sub_dead) for _ in range(5)]

        self.test = self._make_test(10)
        for i, q in enumerate(cpu_qs + dead_qs, start=1):
            self._link(self.test, q, i)

        for i, q in enumerate(cpu_qs):
            correct = (i < 4)
            self._answer(self.test, q, "A" if correct else "B", correct)

        for i, q in enumerate(dead_qs):
            correct = (i == 0)
            self._answer(self.test, q, "A" if correct else "B", correct)

    def test_strength_detected(self):
        s = build_test_summary(self.test)
        self.assertIn("CPU Scheduling", s["strengths"])

    def test_non_strength_excluded(self):
        s = build_test_summary(self.test)
        self.assertNotIn("Deadlocks", s["strengths"])

    def test_strengths_sorted_descending(self):
        s = build_test_summary(self.test)
        accuracies = [
            s["subtopic_breakdown"][name]["accuracy"]
            for name in s["strengths"]
        ]
        self.assertEqual(accuracies, sorted(accuracies, reverse=True))


class TestWeakAreaDetection(AnalysisTestBase):
    """
    CPU Scheduling:    4/5 correct → 80 % → NOT weak
    Memory Management: 0/3 correct → 0 %  → weak
    Deadlocks:         1/4 correct → 25 % → weak
    """

    def setUp(self):
        cpu_qs  = [self._make_question(self.sub_cpu)    for _ in range(5)]
        mem_qs  = [self._make_question(self.sub_memory) for _ in range(3)]
        dead_qs = [self._make_question(self.sub_dead)   for _ in range(4)]

        self.test = self._make_test(12)
        order = 1
        for q in cpu_qs + mem_qs + dead_qs:
            self._link(self.test, q, order)
            order += 1

        for i, q in enumerate(cpu_qs):
            correct = (i < 4)
            self._answer(self.test, q, "A" if correct else "B", correct)
        for q in mem_qs:
            self._answer(self.test, q, "B", False)
        for i, q in enumerate(dead_qs):
            correct = (i == 0)
            self._answer(self.test, q, "A" if correct else "B", correct)

    def test_weak_areas_detected(self):
        s = build_test_summary(self.test)
        self.assertIn("Memory Management", s["weak_areas"])
        self.assertIn("Deadlocks",         s["weak_areas"])

    def test_non_weak_excluded(self):
        s = build_test_summary(self.test)
        self.assertNotIn("CPU Scheduling", s["weak_areas"])

    def test_weak_areas_sorted_ascending(self):
        s = build_test_summary(self.test)
        accuracies = [
            s["subtopic_breakdown"][name]["accuracy"]
            for name in s["weak_areas"]
        ]
        self.assertEqual(accuracies, sorted(accuracies))


class TestCriticalWeakAreaDetection(AnalysisTestBase):
    """
    All-wrong subtopic → critical (accuracy == 0).
    All-unknown subtopic → critical (every answer is X).
    Mixed subtopic with some correct → NOT critical.
    """

    def setUp(self):
        cpu_qs  = [self._make_question(self.sub_cpu)    for _ in range(3)]
        mem_qs  = [self._make_question(self.sub_memory) for _ in range(3)]
        dead_qs = [self._make_question(self.sub_dead)   for _ in range(3)]

        self.test = self._make_test(9)
        order = 1
        for q in cpu_qs + mem_qs + dead_qs:
            self._link(self.test, q, order)
            order += 1

        # CPU: all wrong
        for q in cpu_qs:
            self._answer(self.test, q, "B", False)

        # Memory: all unknown (X)
        for q in mem_qs:
            self._answer(self.test, q, "X", False)

        # Deadlocks: 2 correct, 1 wrong  → NOT critical
        self._answer(self.test, dead_qs[0], "A", True)
        self._answer(self.test, dead_qs[1], "A", True)
        self._answer(self.test, dead_qs[2], "B", False)

    def test_all_wrong_is_critical(self):
        s = build_test_summary(self.test)
        self.assertIn("CPU Scheduling", s["critical_weak_areas"])

    def test_all_unknown_is_critical(self):
        s = build_test_summary(self.test)
        self.assertIn("Memory Management", s["critical_weak_areas"])

    def test_partial_correct_not_critical(self):
        s = build_test_summary(self.test)
        self.assertNotIn("Deadlocks", s["critical_weak_areas"])


class TestUnknownPercentage(AnalysisTestBase):
    """Verify unknown_percentage formula independently."""

    def setUp(self):
        qs = [self._make_question(self.sub_cpu) for _ in range(4)]
        self.test = self._make_test(4)
        for i, q in enumerate(qs, start=1):
            self._link(self.test, q, i)
        # 1 correct, 1 wrong, 2 unknown
        self._answer(self.test, qs[0], "A", True)
        self._answer(self.test, qs[1], "B", False)
        self._answer(self.test, qs[2], "X", False)
        self._answer(self.test, qs[3], "X", False)

    def test_unknown_percentage(self):
        s = build_test_summary(self.test)
        self.assertEqual(s["unknown"], 2)
        self.assertAlmostEqual(s["unknown_percentage"], 50.0, places=2)


class TestCompletionRate(AnalysisTestBase):
    """Completion rate = (correct + wrong) / total * 100; X does not count."""

    def setUp(self):
        qs = [self._make_question(self.sub_cpu) for _ in range(5)]
        self.test = self._make_test(5)
        for i, q in enumerate(qs, start=1):
            self._link(self.test, q, i)
        # 2 correct, 1 wrong, 2 unknown → attempted = 3/5 = 60 %
        self._answer(self.test, qs[0], "A", True)
        self._answer(self.test, qs[1], "A", True)
        self._answer(self.test, qs[2], "B", False)
        self._answer(self.test, qs[3], "X", False)
        self._answer(self.test, qs[4], "X", False)

    def test_completion_rate(self):
        s = build_test_summary(self.test)
        self.assertAlmostEqual(s["completion_rate"], 60.0, places=2)


class TestEmptyTestRaisesValueError(AnalysisTestBase):
    """A test with no MCQTestQuestion rows must raise ValueError."""

    def test_raises_on_empty_test(self):
        test = self._make_test(0)
        with self.assertRaises(ValueError):
            build_test_summary(test)


class TestInProgressRaisesValueError(AnalysisTestBase):
    """An IN_PROGRESS test must raise ValueError."""

    def test_raises_on_in_progress(self):
        test = MCQTest.objects.create(
            user=self.user,
            topic=self.topic,
            total_questions=5,
            status=MCQTest.Status.IN_PROGRESS,
        )
        with self.assertRaises(ValueError):
            build_test_summary(test)


class TestReturnShape(AnalysisTestBase):
    """Verify the returned dictionary is JSON-serialisable and well-shaped."""

    def setUp(self):
        q = self._make_question(self.sub_cpu, Question.Difficulty.EASY)
        self.test = self._make_test(1, score=1, percentage=100.0)
        self._link(self.test, q, 1)
        self._answer(self.test, q, "A", True)

    def test_json_serialisable(self):
        s = build_test_summary(self.test)
        # Must not raise
        serialised = json.dumps(s)
        self.assertIsInstance(serialised, str)

    def test_no_model_instances(self):
        s = build_test_summary(self.test)
        self._assert_no_model_instances(s)

    def _assert_no_model_instances(self, obj):
        from django.db.models import Model
        if isinstance(obj, dict):
            for v in obj.values():
                self._assert_no_model_instances(v)
        elif isinstance(obj, list):
            for item in obj:
                self._assert_no_model_instances(item)
        else:
            self.assertNotIsInstance(
                obj, Model,
                msg=f"Found a Django model instance in the summary: {obj!r}"
            )

    def test_required_keys_present(self):
        s = build_test_summary(self.test)
        required_keys = [
            "test_id", "user_id", "topic", "generated_at",
            "total_questions", "score", "correct", "wrong", "unknown",
            "percentage", "unknown_percentage", "completion_rate",
            "difficulty_breakdown", "subtopic_breakdown",
            "strengths", "weak_areas", "critical_weak_areas",
        ]
        for key in required_keys:
            self.assertIn(key, s, msg=f"Missing key: '{key}'")

    def test_difficulty_breakdown_has_all_keys(self):
        s = build_test_summary(self.test)
        for diff in ("easy", "medium", "hard"):
            bucket = s["difficulty_breakdown"][diff]
            for key in ("correct", "wrong", "unknown", "total", "accuracy"):
                self.assertIn(key, bucket)

    def test_generated_at_is_iso_string(self):
        s = build_test_summary(self.test)
        # Should parse without raising
        dt = datetime.fromisoformat(s["generated_at"])
        self.assertIsInstance(dt, datetime)

    def test_deterministic(self):
        """Calling twice with same data produces identical results (except timestamp)."""
        s1 = build_test_summary(self.test)
        s2 = build_test_summary(self.test)
        for key in s1:
            if key == "generated_at":
                continue
            self.assertEqual(s1[key], s2[key], msg=f"Non-deterministic value for '{key}'")
