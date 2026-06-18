"""
Tests for mcq_engine.services.analysis_cache.get_or_generate_analysis
======================================================================

All calls to generate_ai_analysis() are mocked — no real API calls.

Coverage
--------
✓ Analysis generated on first request (cache miss)
✓ Analysis stored in database after generation
✓ Second request does NOT call AI (cache hit)
✓ Cached data returned correctly on subsequent calls
✓ Failed generation is NOT cached (ai_analysis stays {})
✓ Empty dict (default) triggers generation
✓ update_fields=["ai_analysis"] is used (no other fields mutated)
✓ In-progress test raises ValueError before AI is called
✓ Cache-hit log message emitted
✓ Cache-miss log message emitted
"""

from unittest.mock import call, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from mcq_engine.models import MCQAnswer, MCQTest, MCQTestQuestion, Question, Subtopic, Topic
from mcq_engine.services.analysis_cache import get_or_generate_analysis
from mcq_engine.services.ai_analysis import AIAnalysisError

User = get_user_model()

# ---------------------------------------------------------------------------
# Shared mock payload
# ---------------------------------------------------------------------------

MOCK_ANALYSIS = {
    "performance_summary":     "Good overall performance with minor gaps.",
    "strengths":               ["CPU Scheduling"],
    "weaknesses":              ["Deadlocks"],
    "knowledge_gaps":          ["Virtual Memory"],
    "revision_priority":       ["Deadlocks — highest priority"],
    "study_strategy":          "Use active recall for Deadlocks.",
    "estimated_revision_time": "2–3 hours.",
    "motivation":              "Keep going — you're on the right track.",
}

AI_PATCH = "mcq_engine.services.analysis_cache.generate_ai_analysis"


# ---------------------------------------------------------------------------
# Fixture base
# ---------------------------------------------------------------------------

class CacheTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user     = User.objects.create_user(username="cache_user", password="pass")
        cls.topic    = Topic.objects.create(name="Operating Systems")
        cls.subtopic = Subtopic.objects.create(topic=cls.topic, name="CPU Scheduling")

    def _make_question(self):
        return Question.objects.create(
            topic=self.topic, subtopic=self.subtopic,
            difficulty=Question.Difficulty.MEDIUM,
            question="What is a semaphore?",
            option_a="A", option_b="B", option_c="C", option_d="D",
            correct_option="A",
        )

    def _make_completed_test(self, with_cache=False):
        """
        Return a COMPLETED MCQTest with one answered question.

        Parameters
        ----------
        with_cache : bool
            If True, pre-populate ai_analysis with MOCK_ANALYSIS.
        """
        test = MCQTest.objects.create(
            user=self.user,
            topic=self.topic,
            total_questions=1,
            score=1,
            percentage=100.0,
            status=MCQTest.Status.COMPLETED,
            submitted_at=timezone.now(),
            ai_analysis=MOCK_ANALYSIS if with_cache else {},
        )
        q = self._make_question()
        MCQTestQuestion.objects.create(test=test, question=q, order=1)
        MCQAnswer.objects.create(test=test, question=q, selected_option="A", is_correct=True)
        return test


# ===========================================================================
# Cache miss — first request
# ===========================================================================

class TestCacheMiss(CacheTestBase):

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_generates_analysis_on_first_call(self, mock_ai):
        test = self._make_completed_test()
        result = get_or_generate_analysis(test)
        mock_ai.assert_called_once_with(test)

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_returns_correct_analysis_on_first_call(self, mock_ai):
        test = self._make_completed_test()
        result = get_or_generate_analysis(test)
        self.assertEqual(result, MOCK_ANALYSIS)

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_analysis_persisted_in_database(self, mock_ai):
        test = self._make_completed_test()
        get_or_generate_analysis(test)

        test.refresh_from_db()
        self.assertEqual(test.ai_analysis, MOCK_ANALYSIS)

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_analysis_stored_on_test_instance(self, mock_ai):
        """The in-memory instance is also updated after generation."""
        test = self._make_completed_test()
        get_or_generate_analysis(test)
        self.assertEqual(test.ai_analysis, MOCK_ANALYSIS)

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_cache_miss_log_emitted(self, mock_ai):
        test = self._make_completed_test()
        with self.assertLogs("mcq_engine.services.analysis_cache", level="INFO") as logs:
            get_or_generate_analysis(test)
        self.assertTrue(
            any("cache_miss" in msg for msg in logs.output),
            msg="Expected 'cache_miss' log message on first call",
        )


# ===========================================================================
# Cache hit — subsequent requests
# ===========================================================================

class TestCacheHit(CacheTestBase):

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_second_call_does_not_call_ai(self, mock_ai):
        test = self._make_completed_test(with_cache=True)
        get_or_generate_analysis(test)
        mock_ai.assert_not_called()

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_cached_data_returned_correctly(self, mock_ai):
        test = self._make_completed_test(with_cache=True)
        result = get_or_generate_analysis(test)
        self.assertEqual(result, MOCK_ANALYSIS)

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_two_calls_ai_invoked_only_once(self, mock_ai):
        """First call: cache miss → AI. Second call: cache hit → no AI."""
        test = self._make_completed_test()

        get_or_generate_analysis(test)   # cache miss
        get_or_generate_analysis(test)   # cache hit (in-memory)

        mock_ai.assert_called_once()

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_db_reload_still_hits_cache(self, mock_ai):
        """After a DB refresh the persisted value must be returned without AI."""
        test = self._make_completed_test()
        get_or_generate_analysis(test)           # miss → stored to DB
        mock_ai.reset_mock()

        test.refresh_from_db()                   # reload from DB
        get_or_generate_analysis(test)           # should hit cache
        mock_ai.assert_not_called()

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_cache_hit_log_emitted(self, mock_ai):
        test = self._make_completed_test(with_cache=True)
        with self.assertLogs("mcq_engine.services.analysis_cache", level="INFO") as logs:
            get_or_generate_analysis(test)
        self.assertTrue(
            any("cache_hit" in msg for msg in logs.output),
            msg="Expected 'cache_hit' log message on cached call",
        )


# ===========================================================================
# Failed generation — nothing persisted
# ===========================================================================

class TestFailedGeneration(CacheTestBase):

    @patch(AI_PATCH, side_effect=AIAnalysisError("Groq unavailable"))
    def test_exception_propagates(self, mock_ai):
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            get_or_generate_analysis(test)

    @patch(AI_PATCH, side_effect=AIAnalysisError("Groq unavailable"))
    def test_failed_generation_not_cached_in_memory(self, mock_ai):
        test = self._make_completed_test()
        try:
            get_or_generate_analysis(test)
        except AIAnalysisError:
            pass
        # In-memory field must still be empty
        self.assertEqual(test.ai_analysis, {})

    @patch(AI_PATCH, side_effect=AIAnalysisError("Groq unavailable"))
    def test_failed_generation_not_cached_in_db(self, mock_ai):
        test = self._make_completed_test()
        try:
            get_or_generate_analysis(test)
        except AIAnalysisError:
            pass
        test.refresh_from_db()
        self.assertEqual(test.ai_analysis, {})

    @patch(AI_PATCH, side_effect=ValueError("Test not completed"))
    def test_value_error_propagates(self, mock_ai):
        test = self._make_completed_test()
        with self.assertRaises(ValueError):
            get_or_generate_analysis(test)


# ===========================================================================
# In-progress test guard
# ===========================================================================

class TestInProgressGuard(CacheTestBase):

    @patch(AI_PATCH)
    def test_in_progress_raises_before_ai_called(self, mock_ai):
        test = MCQTest.objects.create(
            user=self.user, topic=self.topic, total_questions=3,
            status=MCQTest.Status.IN_PROGRESS,
        )
        with self.assertRaises(ValueError):
            get_or_generate_analysis(test)
        mock_ai.assert_not_called()


# ===========================================================================
# Empty dict triggers regeneration
# ===========================================================================

class TestEmptyDictTriggersGeneration(CacheTestBase):

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_empty_dict_triggers_generation(self, mock_ai):
        """The default value {} must be treated as a cache miss."""
        test = self._make_completed_test()
        self.assertEqual(test.ai_analysis, {})          # starts empty
        get_or_generate_analysis(test)
        mock_ai.assert_called_once()

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_non_empty_dict_skips_generation(self, mock_ai):
        """Any non-empty dict is a cache hit."""
        test = self._make_completed_test(with_cache=True)
        get_or_generate_analysis(test)
        mock_ai.assert_not_called()


# ===========================================================================
# update_fields correctness
# ===========================================================================

class TestUpdateFields(CacheTestBase):

    @patch(AI_PATCH, return_value=MOCK_ANALYSIS)
    def test_only_ai_analysis_field_written(self, mock_ai):
        """
        Verify that save() is called with update_fields=["ai_analysis"],
        so no other column is accidentally mutated.
        """
        test = self._make_completed_test()

        original_score      = test.score
        original_percentage = test.percentage
        original_status     = test.status

        # Mutate in-memory values that should NOT be persisted
        test.score      = 999
        test.percentage = 0

        get_or_generate_analysis(test)

        test.refresh_from_db()

        # ai_analysis must be saved
        self.assertEqual(test.ai_analysis, MOCK_ANALYSIS)

        # score and percentage must be unchanged in DB (only ai_analysis was in update_fields)
        self.assertEqual(test.score,      original_score)
        self.assertAlmostEqual(float(test.percentage), float(original_percentage), places=2)
        self.assertEqual(test.status,     original_status)
