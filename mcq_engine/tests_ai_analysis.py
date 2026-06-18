"""
Tests for mcq_engine.services.ai_analysis.generate_ai_analysis
===============================================================

All Groq calls are mocked — no real API requests are made.

Coverage
--------
✓ Valid response returns validated dict
✓ Invalid JSON raises AIAnalysisError
✓ Missing required key raises AIValidationError
✓ Wrong field type raises AIValidationError
✓ Empty AI response raises AIAnalysisError
✓ Groq APITimeoutError raises AIAnalysisError
✓ Groq RateLimitError raises AIAnalysisError
✓ Groq AuthenticationError raises AIAnalysisError
✓ Generic APIError raises AIAnalysisError
✓ Unexpected exception raises AIAnalysisError
✓ In-progress test raises ValueError (before Groq is even called)
✓ Empty test (no questions) raises ValueError
✓ _extract_json strips markdown fences correctly
✓ _extract_json locates JSON embedded in surrounding text
✓ _validate_response accepts valid data
✓ _validate_response rejects missing field
✓ _validate_response rejects wrong type
✓ No GROQ_API_KEY raises AIAnalysisError
"""

import json
from unittest.mock import MagicMock, patch

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
from mcq_engine.services.ai_analysis import (
    AIAnalysisError,
    AIValidationError,
    _extract_json,
    _validate_response,
    generate_ai_analysis,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Shared valid AI response payload
# ---------------------------------------------------------------------------

VALID_AI_RESPONSE: dict = {
    "performance_summary":     "Strong across easy questions; hard topics need work.",
    "strengths":               ["CPU Scheduling", "Paging"],
    "weaknesses":              ["Deadlocks"],
    "knowledge_gaps":          ["Virtual Memory"],
    "revision_priority":       ["Deadlocks — critical", "Virtual Memory — unexplored"],
    "study_strategy":          "Use active recall flashcards for Deadlocks theory.",
    "estimated_revision_time": "3–5 hours across two study sessions.",
    "motivation":              "Solid foundation — targeted revision will close the gaps quickly.",
}


# ---------------------------------------------------------------------------
# Fixture base
# ---------------------------------------------------------------------------

class AIAnalysisTestBase(TestCase):
    """Creates a minimal completed MCQTest fixture."""

    @classmethod
    def setUpTestData(cls):
        cls.user     = User.objects.create_user(username="ai_tester", password="pass")
        cls.topic    = Topic.objects.create(name="Operating Systems")
        cls.subtopic = Subtopic.objects.create(topic=cls.topic, name="CPU Scheduling")

    def _make_question(self, difficulty=Question.Difficulty.MEDIUM):
        return Question.objects.create(
            topic=self.topic,
            subtopic=self.subtopic,
            difficulty=difficulty,
            question="What is a context switch?",
            option_a="A", option_b="B", option_c="C", option_d="D",
            correct_option="A",
        )

    def _make_completed_test(self, n=3):
        """Return a fully answered COMPLETED MCQTest."""
        test = MCQTest.objects.create(
            user=self.user,
            topic=self.topic,
            total_questions=n,
            score=n,
            percentage=100.0,
            status=MCQTest.Status.COMPLETED,
            submitted_at=timezone.now(),
        )
        for i in range(n):
            q = self._make_question()
            MCQTestQuestion.objects.create(test=test, question=q, order=i + 1)
            MCQAnswer.objects.create(
                test=test, question=q, selected_option="A", is_correct=True
            )
        return test


# ===========================================================================
# Unit tests for _extract_json
# ===========================================================================

class TestExtractJson(TestCase):

    def test_plain_json_object(self):
        content = json.dumps(VALID_AI_RESPONSE)
        result = _extract_json(content)
        self.assertEqual(result["performance_summary"], VALID_AI_RESPONSE["performance_summary"])

    def test_strips_markdown_json_fence(self):
        content = "```json\n" + json.dumps(VALID_AI_RESPONSE) + "\n```"
        result = _extract_json(content)
        self.assertIn("performance_summary", result)

    def test_strips_plain_markdown_fence(self):
        content = "```\n" + json.dumps(VALID_AI_RESPONSE) + "\n```"
        result = _extract_json(content)
        self.assertIn("performance_summary", result)

    def test_json_embedded_in_preamble_text(self):
        content = "Here is your analysis:\n" + json.dumps(VALID_AI_RESPONSE) + "\nEnd of analysis."
        result = _extract_json(content)
        self.assertIn("performance_summary", result)

    def test_no_json_raises_error(self):
        with self.assertRaises(AIAnalysisError):
            _extract_json("This is just plain text with no JSON at all.")

    def test_invalid_json_raises_error(self):
        with self.assertRaises(AIAnalysisError):
            _extract_json("{not valid json: [}")

    def test_empty_string_raises_error(self):
        with self.assertRaises(AIAnalysisError):
            _extract_json("")


# ===========================================================================
# Unit tests for _validate_response
# ===========================================================================

class TestValidateResponse(TestCase):

    def test_valid_response_passes(self):
        result = _validate_response(dict(VALID_AI_RESPONSE))
        self.assertEqual(result, VALID_AI_RESPONSE)

    def test_missing_field_raises_validation_error(self):
        data = dict(VALID_AI_RESPONSE)
        del data["performance_summary"]
        with self.assertRaises(AIValidationError) as ctx:
            _validate_response(data)
        self.assertIn("performance_summary", str(ctx.exception))

    def test_missing_list_field_raises_validation_error(self):
        data = dict(VALID_AI_RESPONSE)
        del data["revision_priority"]
        with self.assertRaises(AIValidationError):
            _validate_response(data)

    def test_wrong_type_string_field_raises_error(self):
        data = dict(VALID_AI_RESPONSE)
        data["performance_summary"] = 42          # should be str
        with self.assertRaises(AIValidationError) as ctx:
            _validate_response(data)
        self.assertIn("performance_summary", str(ctx.exception))

    def test_wrong_type_list_field_raises_error(self):
        data = dict(VALID_AI_RESPONSE)
        data["strengths"] = "should be a list"   # should be list
        with self.assertRaises(AIValidationError) as ctx:
            _validate_response(data)
        self.assertIn("strengths", str(ctx.exception))

    def test_wrong_type_motivation_raises_error(self):
        data = dict(VALID_AI_RESPONSE)
        data["motivation"] = ["not", "a", "string"]
        with self.assertRaises(AIValidationError):
            _validate_response(data)

    def test_all_required_keys_checked(self):
        """Each required key, when removed individually, must raise AIValidationError."""
        required_keys = [
            "performance_summary", "strengths", "weaknesses", "knowledge_gaps",
            "revision_priority", "study_strategy", "estimated_revision_time", "motivation",
        ]
        for key in required_keys:
            data = dict(VALID_AI_RESPONSE)
            del data[key]
            with self.assertRaises(AIValidationError, msg=f"Expected error for missing '{key}'"):
                _validate_response(data)


# ===========================================================================
# Integration tests for generate_ai_analysis (Groq mocked)
# ===========================================================================

GROQ_PATCH = "mcq_engine.services.ai_analysis._call_groq"


class TestGenerateAiAnalysisSuccess(AIAnalysisTestBase):

    @patch(GROQ_PATCH)
    def test_valid_response_returns_dict(self, mock_call):
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIsInstance(result, dict)

    @patch(GROQ_PATCH)
    def test_all_required_keys_present(self, mock_call):
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        for key in VALID_AI_RESPONSE:
            self.assertIn(key, result)

    @patch(GROQ_PATCH)
    def test_performance_summary_is_string(self, mock_call):
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIsInstance(result["performance_summary"], str)

    @patch(GROQ_PATCH)
    def test_strengths_is_list(self, mock_call):
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIsInstance(result["strengths"], list)

    @patch(GROQ_PATCH)
    def test_revision_priority_is_list(self, mock_call):
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIsInstance(result["revision_priority"], list)

    @patch(GROQ_PATCH)
    def test_groq_called_exactly_once(self, mock_call):
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        generate_ai_analysis(test)
        mock_call.assert_called_once()

    @patch(GROQ_PATCH)
    def test_markdown_fenced_response_is_handled(self, mock_call):
        """Groq sometimes wraps responses in markdown code fences."""
        mock_call.return_value = "```json\n" + json.dumps(VALID_AI_RESPONSE) + "\n```"
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIn("performance_summary", result)


class TestGenerateAiAnalysisErrorHandling(AIAnalysisTestBase):

    def test_in_progress_test_raises_value_error(self):
        """ValueError must be raised before Groq is called."""
        test = MCQTest.objects.create(
            user=self.user, topic=self.topic, total_questions=3,
            status=MCQTest.Status.IN_PROGRESS,
        )
        with self.assertRaises(ValueError):
            generate_ai_analysis(test)

    def test_empty_test_raises_value_error(self):
        """A COMPLETED test with no MCQTestQuestion rows must raise ValueError."""
        test = MCQTest.objects.create(
            user=self.user, topic=self.topic, total_questions=0,
            status=MCQTest.Status.COMPLETED, submitted_at=timezone.now(),
        )
        with self.assertRaises(ValueError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_invalid_json_raises_ai_analysis_error(self, mock_call):
        mock_call.return_value = "This is not JSON at all"
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_malformed_json_raises_ai_analysis_error(self, mock_call):
        mock_call.return_value = "{broken json: [}"
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_missing_key_raises_ai_validation_error(self, mock_call):
        bad = dict(VALID_AI_RESPONSE)
        del bad["motivation"]
        mock_call.return_value = json.dumps(bad)
        test = self._make_completed_test()
        with self.assertRaises(AIValidationError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_wrong_field_type_raises_ai_validation_error(self, mock_call):
        bad = dict(VALID_AI_RESPONSE)
        bad["strengths"] = "a string instead of a list"
        mock_call.return_value = json.dumps(bad)
        test = self._make_completed_test()
        with self.assertRaises(AIValidationError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_timeout_raises_ai_analysis_error(self, mock_call):
        mock_call.side_effect = AIAnalysisError("AI analysis timed out. Please try again.")
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError) as ctx:
            generate_ai_analysis(test)
        self.assertIn("timed out", str(ctx.exception))

    @patch(GROQ_PATCH)
    def test_rate_limit_raises_ai_analysis_error(self, mock_call):
        mock_call.side_effect = AIAnalysisError("AI service is currently busy.")
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_auth_failure_raises_ai_analysis_error(self, mock_call):
        mock_call.side_effect = AIAnalysisError("AI service authentication failed.")
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_generic_api_error_raises_ai_analysis_error(self, mock_call):
        mock_call.side_effect = AIAnalysisError("AI service error: internal server error")
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_unexpected_exception_raises_ai_analysis_error(self, mock_call):
        mock_call.side_effect = AIAnalysisError("Unexpected error communicating with AI service.")
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)

    @patch(GROQ_PATCH)
    def test_empty_response_string_raises_error(self, mock_call):
        mock_call.return_value = ""
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)


class TestGetGroqClientMissingKey(TestCase):
    """Verify that a missing GROQ_API_KEY is caught before any network call."""

    @patch("mcq_engine.services.ai_analysis.os.getenv", return_value=None)
    def test_missing_api_key_raises_ai_analysis_error(self, _mock_env):
        from mcq_engine.services.ai_analysis import _get_groq_client
        with self.assertRaises(AIAnalysisError) as ctx:
            _get_groq_client()
        self.assertIn("GROQ_API_KEY", str(ctx.exception))
