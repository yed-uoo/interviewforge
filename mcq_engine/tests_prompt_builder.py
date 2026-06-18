"""
Tests for mcq_engine.services.prompt_builder.build_analysis_prompt
===================================================================

Coverage
--------
✓ Prompt contains topic
✓ Prompt contains score
✓ Prompt contains difficulty breakdown (easy / medium / hard)
✓ Prompt contains every subtopic name
✓ Prompt contains strengths
✓ Prompt contains weak areas
✓ Prompt contains critical weak areas
✓ Prompt contains JSON output instructions
✓ Prompt is deterministic
✓ Prompt is a plain string (no model instances, no JSON structure)
✓ Empty strengths / weak lists render gracefully
✓ No AI or network imports present in the service module
"""

from django.test import SimpleTestCase

from mcq_engine.services.prompt_builder import build_analysis_prompt


# ---------------------------------------------------------------------------
# Shared fixture factory
# ---------------------------------------------------------------------------

def _make_summary(
    *,
    topic="Operating Systems",
    total=10,
    correct=7,
    wrong=2,
    unknown=1,
    score=7,
    percentage=70.0,
    unknown_percentage=10.0,
    completion_rate=90.0,
    difficulty_breakdown=None,
    subtopic_breakdown=None,
    strengths=None,
    weak_areas=None,
    critical_weak_areas=None,
) -> dict:
    """Return a minimal but realistic summary dictionary."""
    if difficulty_breakdown is None:
        difficulty_breakdown = {
            "easy":   {"total": 4, "correct": 4, "wrong": 0, "unknown": 0, "accuracy": 100.0},
            "medium": {"total": 4, "correct": 3, "wrong": 1, "unknown": 0, "accuracy": 75.0},
            "hard":   {"total": 2, "correct": 0, "wrong": 1, "unknown": 1, "accuracy": 0.0},
        }
    if subtopic_breakdown is None:
        subtopic_breakdown = {
            "CPU Scheduling":    {"total": 5, "correct": 5, "wrong": 0, "unknown": 0, "accuracy": 100.0},
            "Memory Management": {"total": 3, "correct": 2, "wrong": 1, "unknown": 0, "accuracy": 66.67},
            "Deadlocks":         {"total": 2, "correct": 0, "wrong": 1, "unknown": 1, "accuracy": 0.0},
        }
    if strengths is None:
        strengths = ["CPU Scheduling"]
    if weak_areas is None:
        weak_areas = ["Deadlocks"]
    if critical_weak_areas is None:
        critical_weak_areas = ["Deadlocks"]

    return {
        "test_id":            1,
        "user_id":            1,
        "topic":              topic,
        "generated_at":       "2026-06-18T10:00:00+00:00",
        "total_questions":    total,
        "score":              score,
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


# ===========================================================================
# Test classes
# ===========================================================================


class TestPromptContainsTopic(SimpleTestCase):

    def test_topic_in_prompt(self):
        summary = _make_summary(topic="Data Structures and Algorithms")
        prompt = build_analysis_prompt(summary)
        self.assertIn("Data Structures and Algorithms", prompt)

    def test_different_topic_in_prompt(self):
        summary = _make_summary(topic="Computer Networks")
        prompt = build_analysis_prompt(summary)
        self.assertIn("Computer Networks", prompt)


class TestPromptContainsScore(SimpleTestCase):

    def test_score_fraction_in_prompt(self):
        summary = _make_summary(correct=8, score=8, total=10)
        prompt = build_analysis_prompt(summary)
        # Expect something like "8 / 10"
        self.assertIn("8", prompt)
        self.assertIn("10", prompt)

    def test_percentage_in_prompt(self):
        summary = _make_summary(percentage=75.5)
        prompt = build_analysis_prompt(summary)
        self.assertIn("75.5", prompt)

    def test_correct_wrong_unknown_in_prompt(self):
        summary = _make_summary(correct=6, wrong=3, unknown=1)
        prompt = build_analysis_prompt(summary)
        self.assertIn("Correct", prompt)
        self.assertIn("Wrong", prompt)
        self.assertIn("I Don't Know", prompt)

    def test_completion_rate_in_prompt(self):
        summary = _make_summary(completion_rate=80.0)
        prompt = build_analysis_prompt(summary)
        self.assertIn("80.0", prompt)
        self.assertIn("Completion Rate", prompt)

    def test_unknown_percentage_in_prompt(self):
        summary = _make_summary(unknown_percentage=20.0)
        prompt = build_analysis_prompt(summary)
        self.assertIn("20.0", prompt)


class TestPromptContainsDifficultyBreakdown(SimpleTestCase):

    def test_all_three_difficulty_levels_present(self):
        prompt = build_analysis_prompt(_make_summary())
        for level in ("EASY", "MEDIUM", "HARD"):
            self.assertIn(level, prompt,
                          msg=f"Expected difficulty level '{level}' in prompt")

    def test_difficulty_section_heading(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("DIFFICULTY BREAKDOWN", prompt)

    def test_difficulty_accuracy_values(self):
        summary = _make_summary()
        prompt = build_analysis_prompt(summary)
        # Hard accuracy is 0.0 in the default fixture
        self.assertIn("0.0", prompt)
        # Easy accuracy is 100.0
        self.assertIn("100.0", prompt)


class TestPromptContainsEverySubtopic(SimpleTestCase):

    def test_all_default_subtopics_present(self):
        prompt = build_analysis_prompt(_make_summary())
        for subtopic in ("CPU Scheduling", "Memory Management", "Deadlocks"):
            self.assertIn(subtopic, prompt,
                          msg=f"Expected subtopic '{subtopic}' in prompt")

    def test_custom_subtopics_present(self):
        sb = {
            "Paging":           {"total": 3, "correct": 2, "wrong": 1, "unknown": 0, "accuracy": 66.67},
            "Segmentation":     {"total": 2, "correct": 0, "wrong": 0, "unknown": 2, "accuracy": 0.0},
            "Virtual Memory":   {"total": 5, "correct": 5, "wrong": 0, "unknown": 0, "accuracy": 100.0},
        }
        summary = _make_summary(subtopic_breakdown=sb)
        prompt = build_analysis_prompt(summary)
        for name in sb:
            self.assertIn(name, prompt, msg=f"Subtopic '{name}' missing from prompt")

    def test_subtopic_section_heading(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("SUBTOPIC PERFORMANCE", prompt)

    def test_subtopic_accuracy_values_present(self):
        sb = {
            "Scheduling": {"total": 4, "correct": 3, "wrong": 1, "unknown": 0, "accuracy": 75.0},
        }
        summary = _make_summary(subtopic_breakdown=sb)
        prompt = build_analysis_prompt(summary)
        self.assertIn("75.0", prompt)


class TestPromptContainsStrengths(SimpleTestCase):

    def test_strengths_section_heading(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("DETECTED STRENGTHS", prompt)

    def test_strength_name_in_prompt(self):
        summary = _make_summary(strengths=["CPU Scheduling", "Paging"])
        prompt = build_analysis_prompt(summary)
        self.assertIn("CPU Scheduling", prompt)
        self.assertIn("Paging", prompt)

    def test_empty_strengths_renders_gracefully(self):
        summary = _make_summary(strengths=[])
        prompt = build_analysis_prompt(summary)
        self.assertIn("DETECTED STRENGTHS", prompt)
        self.assertIn("none detected", prompt)


class TestPromptContainsWeakAreas(SimpleTestCase):

    def test_weak_areas_section_heading(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("DETECTED WEAK AREAS", prompt)

    def test_weak_area_name_in_prompt(self):
        summary = _make_summary(weak_areas=["Deadlocks", "Segmentation"])
        prompt = build_analysis_prompt(summary)
        self.assertIn("Deadlocks", prompt)
        self.assertIn("Segmentation", prompt)

    def test_empty_weak_areas_renders_gracefully(self):
        summary = _make_summary(weak_areas=[])
        prompt = build_analysis_prompt(summary)
        self.assertIn("DETECTED WEAK AREAS", prompt)
        self.assertIn("none detected", prompt)


class TestPromptContainsCriticalWeakAreas(SimpleTestCase):

    def test_critical_weak_areas_section_heading(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("CRITICAL WEAK AREAS", prompt)

    def test_critical_area_name_in_prompt(self):
        summary = _make_summary(critical_weak_areas=["Virtual Memory", "Deadlocks"])
        prompt = build_analysis_prompt(summary)
        self.assertIn("Virtual Memory", prompt)
        self.assertIn("Deadlocks", prompt)

    def test_empty_critical_areas_renders_gracefully(self):
        summary = _make_summary(critical_weak_areas=[])
        prompt = build_analysis_prompt(summary)
        self.assertIn("CRITICAL WEAK AREAS", prompt)
        self.assertIn("none detected", prompt)


class TestPromptContainsJsonInstructions(SimpleTestCase):

    def test_json_schema_keys_present(self):
        prompt = build_analysis_prompt(_make_summary())
        expected_keys = [
            "performance_summary",
            "strengths",
            "weaknesses",
            "knowledge_gaps",
            "revision_priority",
            "study_strategy",
            "estimated_revision_time",
            "motivation",
        ]
        for key in expected_keys:
            self.assertIn(key, prompt,
                          msg=f"Expected JSON schema key '{key}' in prompt")

    def test_output_format_instruction_present(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("OUTPUT FORMAT", prompt)
        self.assertIn("valid JSON", prompt)

    def test_no_markdown_code_fence_instruction(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIn("No markdown", prompt)
        self.assertIn("no code fences", prompt)


class TestPromptIsDeterministic(SimpleTestCase):

    def test_same_summary_yields_same_prompt(self):
        summary = _make_summary()
        p1 = build_analysis_prompt(summary)
        p2 = build_analysis_prompt(summary)
        self.assertEqual(p1, p2)

    def test_different_topics_yield_different_prompts(self):
        p1 = build_analysis_prompt(_make_summary(topic="OS"))
        p2 = build_analysis_prompt(_make_summary(topic="Networks"))
        self.assertNotEqual(p1, p2)

    def test_different_subtopics_yield_different_prompts(self):
        sb_a = {"Alpha": {"total": 2, "correct": 2, "wrong": 0, "unknown": 0, "accuracy": 100.0}}
        sb_b = {"Beta":  {"total": 2, "correct": 0, "wrong": 2, "unknown": 0, "accuracy": 0.0}}
        p1 = build_analysis_prompt(_make_summary(subtopic_breakdown=sb_a))
        p2 = build_analysis_prompt(_make_summary(subtopic_breakdown=sb_b))
        self.assertNotEqual(p1, p2)


class TestPromptReturnType(SimpleTestCase):

    def test_returns_string(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertIsInstance(prompt, str)

    def test_prompt_is_not_empty(self):
        prompt = build_analysis_prompt(_make_summary())
        self.assertGreater(len(prompt), 200)

    def test_prompt_contains_all_section_headings(self):
        prompt = build_analysis_prompt(_make_summary())
        headings = [
            "ASSESSMENT CONTEXT",
            "ASSESSMENT SUMMARY",
            "DIFFICULTY BREAKDOWN",
            "SUBTOPIC PERFORMANCE",
            "DETECTED STRENGTHS",
            "DETECTED WEAK AREAS",
            "CRITICAL WEAK AREAS",
            "INSTRUCTIONS TO THE AI",
        ]
        for heading in headings:
            self.assertIn(heading, prompt,
                          msg=f"Section heading '{heading}' missing from prompt")


class TestNoAiImports(SimpleTestCase):
    """
    Structural test: ensure the prompt_builder module does not import any
    AI / network library.  This protects against accidental coupling.
    """

    def test_no_groq_import(self):
        import mcq_engine.services.prompt_builder as module
        source = open(module.__file__).read()
        self.assertNotIn("import groq", source.lower())
        self.assertNotIn("from groq", source.lower())

    def test_no_openai_import(self):
        import mcq_engine.services.prompt_builder as module
        source = open(module.__file__).read()
        self.assertNotIn("import openai", source.lower())
        self.assertNotIn("from openai", source.lower())

    def test_no_requests_import(self):
        import mcq_engine.services.prompt_builder as module
        source = open(module.__file__).read()
        self.assertNotIn("import requests", source.lower())
