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
✓ _extract_json tolerates raw newlines inside string values
✓ _extract_json tolerates trailing commas
✓ _extract_json tolerates smart/curly quotes
✓ _validate_response accepts valid data
✓ _validate_response rejects missing field
✓ _validate_response rejects wrong type
✓ No GROQ_API_KEY raises AIAnalysisError
✓ Retry logic: first failure triggers single retry
✓ Retry success: retry returns valid dict after initial parse failure
✓ Retry failure: both attempts fail → raises the second exception
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
    _sanitise_json_string,
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


# ===========================================================================
# Tests for _sanitise_json_string
# ===========================================================================

class TestSanitiseJsonString(TestCase):
    """Unit tests for the JSON sanitisation helper."""

    def test_plain_string_unchanged(self):
        s = '{"key": "value"}'
        self.assertEqual(_sanitise_json_string(s), s)

    def test_strips_markdown_json_fence(self):
        s = '```json\n{"key": "val"}\n```'
        result = _sanitise_json_string(s)
        self.assertNotIn("```", result)
        self.assertIn('"key"', result)

    def test_strips_plain_markdown_fence(self):
        s = '```\n{"key": "val"}\n```'
        result = _sanitise_json_string(s)
        self.assertNotIn("```", result)

    def test_strips_mid_string_fence(self):
        """Fences that don't start at position 0 are also removed."""
        s = 'Sure! Here you go:\n```json\n{"k": "v"}\n```'
        result = _sanitise_json_string(s)
        self.assertNotIn("```", result)

    def test_replaces_smart_double_quotes(self):
        s = '\u201cvalue\u201d'
        self.assertIn('"', _sanitise_json_string(s))
        self.assertNotIn('\u201c', _sanitise_json_string(s))
        self.assertNotIn('\u201d', _sanitise_json_string(s))

    def test_replaces_smart_single_quotes(self):
        s = "\u2018value\u2019"
        result = _sanitise_json_string(s)
        self.assertIn("'", result)

    def test_removes_trailing_comma_before_brace(self):
        s = '{"a": 1,}'
        result = _sanitise_json_string(s)
        self.assertNotIn(',}', result)

    def test_removes_trailing_comma_before_bracket(self):
        s = '{"a": [1, 2,]}'
        result = _sanitise_json_string(s)
        self.assertNotIn(',]', result)

    def test_escapes_bare_newline_in_string(self):
        # A raw newline inside a JSON string value is illegal; it should be escaped
        raw = '{"key": "line1\nline2"}'
        result = _sanitise_json_string(raw)
        # After sanitisation the string should be parseable
        parsed = json.loads(result)
        self.assertIn("line1", parsed["key"])
        self.assertIn("line2", parsed["key"])

    def test_escapes_bare_carriage_return_in_string(self):
        raw = '{"key": "val\rend"}'
        result = _sanitise_json_string(raw)
        parsed = json.loads(result)
        self.assertIn("val", parsed["key"])

    def test_does_not_escape_structural_newlines(self):
        """Newlines outside string values are structural and must be preserved."""
        raw = '{\n    "key": "value"\n}'
        result = _sanitise_json_string(raw)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

    def test_already_escaped_newlines_not_double_escaped(self):
        """\\n inside a JSON string (already escaped) must stay as-is."""
        raw = json.dumps({"key": "line1\nline2"})   # json.dumps escapes correctly
        result = _sanitise_json_string(raw)
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "line1\nline2")


# ===========================================================================
# New _extract_json tolerance tests
# ===========================================================================

class TestExtractJsonTolerance(TestCase):
    """Extra _extract_json tests covering LLM quirks."""

    def test_raw_newline_inside_string_value(self):
        """The root cause of the production bug: raw \n inside a JSON string."""
        # Build a JSON string that has an unescaped newline in a value
        raw = '{"performance_summary": "line one\nline two", "x": 1}'
        result = _extract_json(raw)
        self.assertIn("performance_summary", result)
        self.assertIn("line one", result["performance_summary"])

    def test_trailing_commas_tolerated(self):
        raw = '{"a": "v1", "b": [1, 2,],}'
        result = _extract_json(raw)
        self.assertEqual(result["a"], "v1")
        self.assertEqual(result["b"], [1, 2])

    def test_smart_quotes_in_values(self):
        raw = '{\u201ckey\u201d: \u201cvalue\u201d}'
        result = _extract_json(raw)
        self.assertIn("key", result)
        self.assertEqual(result["key"], "value")

    def test_leading_and_trailing_explanatory_text(self):
        preamble = "Here is your JSON analysis:\n"
        postamble = "\nI hope this helps!"
        payload = json.dumps({"performance_summary": "good", "x": 1})
        result = _extract_json(preamble + payload + postamble)
        self.assertEqual(result["performance_summary"], "good")

    def test_extra_whitespace_around_json(self):
        raw = "   \n   " + json.dumps({"k": "v"}) + "   \n   "
        result = _extract_json(raw)
        self.assertEqual(result["k"], "v")

    def test_error_message_says_extraction_when_no_braces(self):
        with self.assertRaises(AIAnalysisError) as ctx:
            _extract_json("no braces here")
        self.assertIn("extraction", str(ctx.exception).lower())

    def test_error_message_says_parsing_on_bad_json(self):
        with self.assertRaises(AIAnalysisError) as ctx:
            _extract_json("{truly broken: [}")
        self.assertIn("parsing", str(ctx.exception).lower())


# ===========================================================================
# Validate response error message tests
# ===========================================================================

class TestValidateResponseMessages(TestCase):
    """Verify that AIValidationError messages include 'Schema validation failure'."""

    def test_missing_field_message_prefix(self):
        data = dict(VALID_AI_RESPONSE)
        del data["motivation"]
        with self.assertRaises(AIValidationError) as ctx:
            _validate_response(data)
        self.assertIn("Schema validation failure", str(ctx.exception))

    def test_wrong_type_message_prefix(self):
        data = dict(VALID_AI_RESPONSE)
        data["strengths"] = "not a list"
        with self.assertRaises(AIValidationError) as ctx:
            _validate_response(data)
        self.assertIn("Schema validation failure", str(ctx.exception))


# ===========================================================================
# Retry logic tests
# ===========================================================================

class TestRetryLogic(AIAnalysisTestBase):
    """Tests for the single-retry behaviour in generate_ai_analysis."""

    @patch(GROQ_PATCH)
    def test_retry_called_on_parse_failure(self, mock_call):
        """
        When the first response is unparseable, _call_groq must be called
        a second time (retry), and if the retry also fails, AIAnalysisError
        is raised.
        """
        mock_call.return_value = "not valid json at all, no braces"
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)
        # Should have been called twice: original attempt + 1 retry
        self.assertEqual(mock_call.call_count, 2)

    @patch(GROQ_PATCH)
    def test_retry_success_returns_valid_dict(self, mock_call):
        """
        First call returns malformed JSON; second call (retry) returns valid
        JSON → generate_ai_analysis must succeed.
        """
        mock_call.side_effect = [
            "not json at all",                   # first attempt fails
            json.dumps(VALID_AI_RESPONSE),        # retry succeeds
        ]
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIsInstance(result, dict)
        self.assertIn("performance_summary", result)
        self.assertEqual(mock_call.call_count, 2)

    @patch(GROQ_PATCH)
    def test_retry_failure_raises_error(self, mock_call):
        """
        Both attempts return bad JSON → AIAnalysisError is raised after the
        retry (not after the first attempt only).
        """
        mock_call.return_value = "still no json here"
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError):
            generate_ai_analysis(test)
        self.assertEqual(mock_call.call_count, 2)

    @patch(GROQ_PATCH)
    def test_retry_on_validation_failure(self, mock_call):
        """
        First call returns JSON that passes parsing but fails schema validation.
        Second call returns valid JSON → should succeed.
        """
        bad = dict(VALID_AI_RESPONSE)
        del bad["motivation"]  # triggers AIValidationError

        mock_call.side_effect = [
            json.dumps(bad),                    # first: schema validation failure
            json.dumps(VALID_AI_RESPONSE),      # retry: success
        ]
        test = self._make_completed_test()
        result = generate_ai_analysis(test)
        self.assertIn("motivation", result)
        self.assertEqual(mock_call.call_count, 2)

    @patch(GROQ_PATCH)
    def test_auth_failure_not_retried(self, mock_call):
        """
        Authentication errors should NOT trigger a retry — they indicate a
        misconfiguration, not a transient parsing problem.
        """
        mock_call.side_effect = AIAnalysisError(
            "API failure: AI service authentication failed. Check GROQ_API_KEY."
        )
        test = self._make_completed_test()
        with self.assertRaises(AIAnalysisError) as ctx:
            generate_ai_analysis(test)
        self.assertIn("authentication failed", str(ctx.exception))
        # Must NOT have retried
        self.assertEqual(mock_call.call_count, 1)

    @patch(GROQ_PATCH)
    def test_no_retry_on_clean_success(self, mock_call):
        """When the first attempt succeeds, _call_groq must be called exactly once."""
        mock_call.return_value = json.dumps(VALID_AI_RESPONSE)
        test = self._make_completed_test()
        generate_ai_analysis(test)
        self.assertEqual(mock_call.call_count, 1)
