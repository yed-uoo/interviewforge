from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from mcq_engine.models import Topic, Subtopic, Question, MCQTest, MCQTestQuestion, MCQAnswer
from mcq_engine.services.test_generator import _compute_difficulty_budget, DIFFICULTY_PROFILES
from mcq_engine.services.analysis import build_test_summary
from mcq_engine.services.prompt_builder import build_analysis_prompt

User = get_user_model()


class MCQTestWorkflowTestCase(TestCase):
    def setUp(self):
        # Create users
        self.user = User.objects.create_user(username='candidate', password='password123')
        self.other_user = User.objects.create_user(username='other', password='password123')

        # Create topic & subtopic
        self.topic = Topic.objects.create(name='Python programming')
        self.subtopic = Subtopic.objects.create(topic=self.topic, name='Data structures')

        # Create enough questions for a 5-question FRESHER test
        # FRESHER budget for 5: Easy 4, Medium 1, Hard 0
        self.questions = []
        for i in range(5):
            # 4 easy + 1 medium to satisfy FRESHER 5-question budget
            difficulty = Question.Difficulty.EASY if i < 4 else Question.Difficulty.MEDIUM
            self.questions.append(
                Question.objects.create(
                    topic=self.topic,
                    subtopic=self.subtopic,
                    difficulty=difficulty,
                    question=f'What is Python list question {i}?',
                    option_a='Answer A',
                    option_b='Answer B',
                    option_c='Answer C',
                    option_d='Answer D',
                    correct_option='A',
                    explanation='A is correct because...'
                )
            )

    def test_setup_view_requires_login(self):
        response = self.client.get(reverse('mcq_setup'))
        self.assertRedirects(response, f'/accounts/login/?next={reverse("mcq_setup")}')

    def test_setup_view_render(self):
        self.client.login(username='candidate', password='password123')
        response = self.client.get(reverse('mcq_setup'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'mcq_engine/setup.html')
        self.assertContains(response, 'Setup Practice Session')

    def test_setup_view_post_creates_session(self):
        self.client.login(username='candidate', password='password123')
        response = self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'experience_level': 'FRESHER',
            'question_count': 5
        })
        
        # Should redirect to test session page
        mcq_test = MCQTest.objects.first()
        self.assertIsNotNone(mcq_test)
        self.assertEqual(mcq_test.user, self.user)
        self.assertEqual(mcq_test.topic, self.topic)
        self.assertEqual(mcq_test.total_questions, 5)
        self.assertEqual(mcq_test.status, MCQTest.Status.IN_PROGRESS)
        self.assertEqual(mcq_test.experience_level, 'FRESHER')
        
        self.assertRedirects(response, reverse('mcq_test_session', args=[mcq_test.id]))
        
        # Check that MCQTestQuestion entries were created
        self.assertEqual(MCQTestQuestion.objects.filter(test=mcq_test).count(), 5)

    def test_setup_view_insufficient_questions(self):
        self.client.login(username='candidate', password='password123')
        # FRESHER 10-question budget: Easy=8. We only have 4 easy → error
        response = self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'experience_level': 'FRESHER',
            'question_count': 10
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Need 8 questions but only 4 available.")

    def test_session_view_requires_login(self):
        mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic, total_questions=5, status=MCQTest.Status.IN_PROGRESS
        )
        response = self.client.get(reverse('mcq_test_session', args=[mcq_test.id]))
        self.assertRedirects(response, f'/accounts/login/?next={reverse("mcq_test_session", args=[mcq_test.id])}')

    def test_session_view_access_control(self):
        # Create test belonging to self.user
        mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic, total_questions=5, status=MCQTest.Status.IN_PROGRESS
        )
        # Login other_user
        self.client.login(username='other', password='password123')
        response = self.client.get(reverse('mcq_test_session', args=[mcq_test.id]))
        self.assertEqual(response.status_code, 403)

    def test_session_view_render(self):
        self.client.login(username='candidate', password='password123')
        # Setup test session first
        self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'experience_level': 'FRESHER',
            'question_count': 5
        })
        mcq_test = MCQTest.objects.first()
        
        response = self.client.get(reverse('mcq_test_session', args=[mcq_test.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'mcq_engine/session.html')
        self.assertContains(response, 'What is Python list question')

    def test_session_submission_grading(self):
        self.client.login(username='candidate', password='password123')
        # Setup test session
        self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'experience_level': 'FRESHER',
            'question_count': 5
        })
        mcq_test = MCQTest.objects.first()
        test_questions = MCQTestQuestion.objects.filter(test=mcq_test).order_by('order')
        
        # Prepare mock response data
        # We will answer 3 questions correctly ('A'), 1 incorrectly ('B'), and skip 1 ('X')
        post_data = {}
        post_data[f'question_{test_questions[0].question.id}'] = 'A'  # correct
        post_data[f'question_{test_questions[1].question.id}'] = 'A'  # correct
        post_data[f'question_{test_questions[2].question.id}'] = 'A'  # correct
        post_data[f'question_{test_questions[3].question.id}'] = 'B'  # incorrect
        post_data[f'question_{test_questions[4].question.id}'] = 'X'  # skipped
        
        response = self.client.post(reverse('mcq_test_session', args=[mcq_test.id]), post_data)
        
        # Verify redirect to results page
        self.assertRedirects(response, reverse('mcq_results', args=[mcq_test.id]))
        
        # Verify MCQTest metrics
        mcq_test.refresh_from_db()
        self.assertEqual(mcq_test.status, MCQTest.Status.COMPLETED)
        self.assertEqual(mcq_test.score, 3)
        self.assertEqual(float(mcq_test.percentage), 60.00)
        self.assertIsNotNone(mcq_test.submitted_at)
        
        # Verify MCQAnswer records
        self.assertEqual(MCQAnswer.objects.filter(test=mcq_test).count(), 5)
        self.assertEqual(MCQAnswer.objects.filter(test=mcq_test, is_correct=True).count(), 3)
        self.assertEqual(MCQAnswer.objects.filter(test=mcq_test, selected_option='X').count(), 1)

    def test_results_view_access_control(self):
        mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic, total_questions=5, score=3, percentage=60.0,
            status=MCQTest.Status.COMPLETED, submitted_at=timezone.now()
        )
        self.client.login(username='other', password='password123')
        response = self.client.get(reverse('mcq_results', args=[mcq_test.id]))
        self.assertEqual(response.status_code, 403)

    def test_results_view_render(self):
        self.client.login(username='candidate', password='password123')
        # Setup and complete test session
        self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'experience_level': 'FRESHER',
            'question_count': 5
        })
        mcq_test = MCQTest.objects.first()
        test_questions = MCQTestQuestion.objects.filter(test=mcq_test)
        
        post_data = {f'question_{tq.question.id}': 'A' for tq in test_questions}
        self.client.post(reverse('mcq_test_session', args=[mcq_test.id]), post_data)
        
        response = self.client.get(reverse('mcq_results', args=[mcq_test.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'mcq_engine/result.html')
        self.assertContains(response, 'Revision Breakdown')
        self.assertContains(response, '100.00%')
        self.assertContains(response, 'Outstanding Performance')  # updated: 90-100% tier label


# =============================================================================
# Phase 14 — Experience-Aware Assessment Tests
# =============================================================================

class ExperienceAwareBudgetTestCase(TestCase):
    """
    Tests for _compute_difficulty_budget() across all profiles and question counts.
    Verifies:
      - Correct per-bucket values
      - sum(budget.values()) == question_count always
      - FRESHER hard bucket is always 0
    """

    COUNTS = [5, 10, 15, 20]

    def _assert_budget_total(self, count, level):
        """Helper: budget must always sum exactly to question_count."""
        budget = _compute_difficulty_budget(count, level)
        total = sum(budget.values())
        self.assertEqual(
            total, count,
            f"Budget for {level}/{count} questions summed to {total}, expected {count}. "
            f"Budget: {budget}"
        )

    # ── Sum invariant across all profiles ───────────────────────────────────

    def test_budget_sum_fresher(self):
        for count in self.COUNTS:
            with self.subTest(count=count):
                self._assert_budget_total(count, "FRESHER")

    def test_budget_sum_junior(self):
        for count in self.COUNTS:
            with self.subTest(count=count):
                self._assert_budget_total(count, "JUNIOR")

    def test_budget_sum_mid_level(self):
        for count in self.COUNTS:
            with self.subTest(count=count):
                self._assert_budget_total(count, "MID_LEVEL")

    def test_budget_sum_senior(self):
        for count in self.COUNTS:
            with self.subTest(count=count):
                self._assert_budget_total(count, "SENIOR")

    # ── FRESHER hard bucket must always be zero ─────────────────────────────

    def test_fresher_hard_is_zero(self):
        from mcq_engine.models import Question
        for count in self.COUNTS:
            with self.subTest(count=count):
                budget = _compute_difficulty_budget(count, "FRESHER")
                self.assertEqual(
                    budget[Question.Difficulty.HARD], 0,
                    f"FRESHER hard bucket should be 0 for {count} questions, got {budget}"
                )

    # ── Exact values for 10 questions ───────────────────────────────────────

    def test_fresher_10_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(10, "FRESHER")
        self.assertEqual(budget[Question.Difficulty.EASY], 8)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 2)
        self.assertEqual(budget[Question.Difficulty.HARD], 0)

    def test_junior_10_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(10, "JUNIOR")
        self.assertEqual(budget[Question.Difficulty.EASY], 6)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 2)
        self.assertEqual(budget[Question.Difficulty.HARD], 2)

    def test_mid_level_10_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(10, "MID_LEVEL")
        self.assertEqual(budget[Question.Difficulty.EASY], 5)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 3)
        self.assertEqual(budget[Question.Difficulty.HARD], 2)

    def test_senior_10_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(10, "SENIOR")
        self.assertEqual(budget[Question.Difficulty.EASY], 4)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 3)
        self.assertEqual(budget[Question.Difficulty.HARD], 3)

    # ── Exact values for 5 questions ────────────────────────────────────────

    def test_fresher_5_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(5, "FRESHER")
        self.assertEqual(budget[Question.Difficulty.EASY], 4)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 1)
        self.assertEqual(budget[Question.Difficulty.HARD], 0)

    def test_junior_5_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(5, "JUNIOR")
        # 60%=3, 20%=1, 20%=1 → sum=5
        self.assertEqual(budget[Question.Difficulty.EASY], 3)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 1)
        self.assertEqual(budget[Question.Difficulty.HARD], 1)

    def test_mid_level_5_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(5, "MID_LEVEL")
        # floor(2.5)=2, floor(1.5)=1, floor(1.0)=1 → sum=4 → remainder 1 → easy gets +1 → 3,1,1
        self.assertEqual(budget[Question.Difficulty.EASY], 3)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 1)
        self.assertEqual(budget[Question.Difficulty.HARD], 1)

    def test_senior_5_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(5, "SENIOR")
        # floor(2.0)=2, floor(1.5)=1, floor(1.5)=1 → sum=4 → remainder 1 → easy gets +1 → 3,1,1
        self.assertEqual(budget[Question.Difficulty.EASY], 3)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 1)
        self.assertEqual(budget[Question.Difficulty.HARD], 1)

    # ── Exact values for 20 questions ───────────────────────────────────────

    def test_fresher_20_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(20, "FRESHER")
        self.assertEqual(budget[Question.Difficulty.EASY], 16)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 4)
        self.assertEqual(budget[Question.Difficulty.HARD], 0)

    def test_senior_20_questions(self):
        from mcq_engine.models import Question
        budget = _compute_difficulty_budget(20, "SENIOR")
        self.assertEqual(budget[Question.Difficulty.EASY], 8)
        self.assertEqual(budget[Question.Difficulty.MEDIUM], 6)
        self.assertEqual(budget[Question.Difficulty.HARD], 6)


class ExperienceLevelFormValidationTestCase(TestCase):
    """Tests for experience_level field validation in AssessmentConfigForm."""

    def setUp(self):
        self.topic = Topic.objects.create(name='Test Topic')

    def test_valid_experience_levels_accepted(self):
        from mcq_engine.forms import AssessmentConfigForm
        for level in ['FRESHER', 'JUNIOR', 'MID_LEVEL', 'SENIOR']:
            with self.subTest(level=level):
                form = AssessmentConfigForm(data={
                    'topic': self.topic.id,
                    'experience_level': level,
                    'question_count': 5,
                })
                self.assertTrue(form.is_valid(), f"Form should be valid for level={level}: {form.errors}")

    def test_invalid_experience_level_rejected(self):
        from mcq_engine.forms import AssessmentConfigForm
        form = AssessmentConfigForm(data={
            'topic': self.topic.id,
            'experience_level': 'EXPERT',   # not a valid choice
            'question_count': 5,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('experience_level', form.errors)

    def test_missing_experience_level_rejected(self):
        from mcq_engine.forms import AssessmentConfigForm
        form = AssessmentConfigForm(data={
            'topic': self.topic.id,
            'question_count': 5,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('experience_level', form.errors)


class ExperienceLevelPersistenceTestCase(TestCase):
    """Tests that experience_level is correctly saved on MCQTest."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='pass123')
        self.topic = Topic.objects.create(name='Databases')
        self.subtopic = Subtopic.objects.create(topic=self.topic, name='SQL')

        # Create 4 easy + 1 medium for FRESHER 5-question budget
        for i in range(4):
            Question.objects.create(
                topic=self.topic, subtopic=self.subtopic,
                difficulty=Question.Difficulty.EASY,
                question=f'Easy question {i}', option_a='A', option_b='B',
                option_c='C', option_d='D', correct_option='A',
            )
        Question.objects.create(
            topic=self.topic, subtopic=self.subtopic,
            difficulty=Question.Difficulty.MEDIUM,
            question='Medium question', option_a='A', option_b='B',
            option_c='C', option_d='D', correct_option='A',
        )

    def _post_setup(self, level):
        self.client.login(username='testuser', password='pass123')
        self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'experience_level': level,
            'question_count': 5,
        })
        return MCQTest.objects.filter(user=self.user).first()

    def test_fresher_persisted(self):
        test = self._post_setup('FRESHER')
        self.assertIsNotNone(test)
        self.assertEqual(test.experience_level, 'FRESHER')

    def test_junior_persisted(self):
        # Need 3 easy + 1 med + 1 hard for JUNIOR 5q (3,1,1)
        Question.objects.create(
            topic=self.topic, subtopic=self.subtopic,
            difficulty=Question.Difficulty.HARD,
            question='Hard question', option_a='A', option_b='B',
            option_c='C', option_d='D', correct_option='A',
        )
        test = self._post_setup('JUNIOR')
        self.assertIsNotNone(test)
        self.assertEqual(test.experience_level, 'JUNIOR')


class HistoryPageExperienceLevelTestCase(TestCase):
    """Tests that the history page renders experience level badges."""

    def setUp(self):
        self.user = User.objects.create_user(username='histuser', password='pass123')
        self.topic = Topic.objects.create(name='Algorithms')
        self.mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic,
            total_questions=10, score=8, percentage=80.0,
            status=MCQTest.Status.COMPLETED,
            experience_level=MCQTest.ExperienceLevel.JUNIOR,
            submitted_at=timezone.now(),
        )

    def test_history_shows_experience_level(self):
        self.client.login(username='histuser', password='pass123')
        response = self.client.get(reverse('mcq_history'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Junior')   # get_experience_level_display value

    def test_history_experience_column_header(self):
        self.client.login(username='histuser', password='pass123')
        response = self.client.get(reverse('mcq_history'))
        self.assertContains(response, 'Experience')


class ResultsPageExperienceLevelTestCase(TestCase):
    """Tests that the results page renders experience level in banners."""

    def setUp(self):
        self.user = User.objects.create_user(username='resuser', password='pass123')
        self.topic = Topic.objects.create(name='OS')
        self.subtopic = Subtopic.objects.create(topic=self.topic, name='Scheduling')
        self.mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic,
            total_questions=5, score=5, percentage=100.0,
            status=MCQTest.Status.COMPLETED,
            experience_level=MCQTest.ExperienceLevel.MID_LEVEL,
            submitted_at=timezone.now(),
        )
        q = Question.objects.create(
            topic=self.topic, subtopic=self.subtopic,
            difficulty=Question.Difficulty.EASY,
            question='Test Q', option_a='A', option_b='B',
            option_c='C', option_d='D', correct_option='A',
        )
        tq = MCQTestQuestion.objects.create(test=self.mcq_test, question=q, order=1)
        MCQAnswer.objects.create(
            test=self.mcq_test, question=q,
            selected_option='A', is_correct=True,
        )

    def test_results_show_experience_level(self):
        self.client.login(username='resuser', password='pass123')
        response = self.client.get(reverse('mcq_results', args=[self.mcq_test.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Experience Level')
        self.assertContains(response, 'Mid-Level')   # get_experience_level_display


class BuildTestSummaryExperienceLevelTestCase(TestCase):
    """Tests that build_test_summary() includes experience_level in the returned dict."""

    def setUp(self):
        self.user = User.objects.create_user(username='sumuser', password='pass123')
        self.topic = Topic.objects.create(name='Networks')
        self.subtopic = Subtopic.objects.create(topic=self.topic, name='TCP/IP')
        self.mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic,
            total_questions=1, score=1, percentage=100.0,
            status=MCQTest.Status.COMPLETED,
            experience_level=MCQTest.ExperienceLevel.SENIOR,
            submitted_at=timezone.now(),
        )
        q = Question.objects.create(
            topic=self.topic, subtopic=self.subtopic,
            difficulty=Question.Difficulty.HARD,
            question='Hard Q', option_a='A', option_b='B',
            option_c='C', option_d='D', correct_option='A',
        )
        MCQTestQuestion.objects.create(test=self.mcq_test, question=q, order=1)
        MCQAnswer.objects.create(
            test=self.mcq_test, question=q,
            selected_option='A', is_correct=True,
        )

    def test_summary_includes_experience_level(self):
        summary = build_test_summary(self.mcq_test)
        self.assertIn('experience_level', summary)
        self.assertEqual(summary['experience_level'], 'SENIOR')


class PromptBuilderExperienceLevelTestCase(TestCase):
    """Tests that the AI prompt includes Experience Level context."""

    def setUp(self):
        self.user = User.objects.create_user(username='promptuser', password='pass123')
        self.topic = Topic.objects.create(name='DBMS')
        self.subtopic = Subtopic.objects.create(topic=self.topic, name='Joins')
        self.mcq_test = MCQTest.objects.create(
            user=self.user, topic=self.topic,
            total_questions=1, score=1, percentage=100.0,
            status=MCQTest.Status.COMPLETED,
            experience_level=MCQTest.ExperienceLevel.FRESHER,
            submitted_at=timezone.now(),
        )
        q = Question.objects.create(
            topic=self.topic, subtopic=self.subtopic,
            difficulty=Question.Difficulty.EASY,
            question='Easy Q', option_a='A', option_b='B',
            option_c='C', option_d='D', correct_option='A',
        )
        MCQTestQuestion.objects.create(test=self.mcq_test, question=q, order=1)
        MCQAnswer.objects.create(
            test=self.mcq_test, question=q,
            selected_option='A', is_correct=True,
        )

    def test_prompt_contains_experience_level(self):
        summary = build_test_summary(self.mcq_test)
        prompt = build_analysis_prompt(summary)
        self.assertIn('Experience Level', prompt)
        self.assertIn('FRESHER', prompt)
