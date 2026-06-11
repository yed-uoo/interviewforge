from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from mcq_engine.models import Topic, Subtopic, Question, MCQTest, MCQTestQuestion, MCQAnswer

User = get_user_model()


class MCQTestWorkflowTestCase(TestCase):
    def setUp(self):
        # Create users
        self.user = User.objects.create_user(username='candidate', password='password123')
        self.other_user = User.objects.create_user(username='other', password='password123')

        # Create topic & subtopic
        self.topic = Topic.objects.create(name='Python programming')
        self.subtopic = Subtopic.objects.create(topic=self.topic, name='Data structures')

        # Create enough questions for a 5-question test
        # Budget: 40% Easy (2), 30% Medium (2), 30% Hard (1) -> total 5
        self.questions = []
        for i in range(5):
            difficulty = Question.Difficulty.EASY if i < 2 else (Question.Difficulty.MEDIUM if i < 4 else Question.Difficulty.HARD)
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
            'question_count': 5
        })
        
        # Should redirect to test session page
        mcq_test = MCQTest.objects.first()
        self.assertIsNotNone(mcq_test)
        self.assertEqual(mcq_test.user, self.user)
        self.assertEqual(mcq_test.topic, self.topic)
        self.assertEqual(mcq_test.total_questions, 5)
        self.assertEqual(mcq_test.status, MCQTest.Status.IN_PROGRESS)
        
        self.assertRedirects(response, reverse('mcq_test_session', args=[mcq_test.id]))
        
        # Check that MCQTestQuestion entries were created
        self.assertEqual(MCQTestQuestion.objects.filter(test=mcq_test).count(), 5)

    def test_setup_view_insufficient_questions(self):
        self.client.login(username='candidate', password='password123')
        # Requesting 10 questions when only 5 exist should raise error handled on form
        response = self.client.post(reverse('mcq_setup'), {
            'topic': self.topic.id,
            'question_count': 10
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Need 4 questions but only 2 available.")

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
        self.assertContains(response, 'Passed')
