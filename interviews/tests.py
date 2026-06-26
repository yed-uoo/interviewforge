from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from unittest.mock import patch

from resume_analyzer.models import Resume
from resume_analyzer.utils import compute_content_hash
from .resume_context import get_resume_context

class InterviewResumeCacheTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(
			username="tester",
			password="password123"
		)

	def _make_upload(self):
		return SimpleUploadedFile(
			"resume.pdf",
			b"%PDF-1.4 test content",
			content_type="application/pdf"
		)

	@patch("interviews.resume_context.analyze_resume")
	@patch("interviews.resume_context.validate_resume_document", return_value=True)
	@patch("interviews.resume_context.extract_text_from_pdf", return_value="Hello resume")
	def test_interview_cache_hit_reuses_analysis_and_skips_analyze_resume(
		self,
		mock_extract_text,
		mock_validate,
		mock_analyze
	):
		content_hash = compute_content_hash("Hello resume")
		cached_resume = Resume.objects.create(
			user=self.user,
			file=self._make_upload(),
			extracted_text="Hello resume",
			ats_score=88,
			analysis_data={"ats_score": 88, "strengths": ["Cached"]},
			content_hash=content_hash
		)

		context = get_resume_context(
			user=self.user,
			uploaded_file=self._make_upload()
		)

		self.assertEqual(mock_analyze.call_count, 0)
		self.assertEqual(Resume.objects.count(), 2)

		new_resume = Resume.objects.order_by("-id").first()
		self.assertEqual(new_resume.ats_score, cached_resume.ats_score)
		self.assertEqual(new_resume.analysis_data, cached_resume.analysis_data)
		self.assertEqual(new_resume.content_hash, cached_resume.content_hash)
		self.assertTrue(context["used_resume_context"])

	@patch("interviews.resume_context.analyze_resume")
	@patch("interviews.resume_context.validate_resume_document", return_value=True)
	@patch("interviews.resume_context.extract_text_from_pdf", return_value="Hello resume")
	def test_interview_cache_miss_calls_analyze_resume(
		self,
		mock_extract_text,
		mock_validate,
		mock_analyze
	):
		mock_analyze.return_value = {
			"ats_score": 80,
			"strengths": ["Strong backend skills"]
		}

		context = get_resume_context(
			user=self.user,
			uploaded_file=self._make_upload()
		)

		self.assertEqual(mock_analyze.call_count, 1)
		self.assertEqual(Resume.objects.count(), 1)

		resume = Resume.objects.first()
		self.assertEqual(resume.ats_score, 80)
		self.assertEqual(resume.analysis_data, mock_analyze.return_value)
		self.assertEqual(
			resume.content_hash,
			compute_content_hash("Hello resume")
		)
		self.assertTrue(context["used_resume_context"])

	@patch("interviews.resume_context.analyze_resume")
	@patch("interviews.resume_context.validate_resume_document", return_value=True)
	@patch("interviews.resume_context.extract_text_from_pdf", return_value="Hello resume")
	def test_interview_cache_miss_logs_event(
		self,
		mock_extract_text,
		mock_validate,
		mock_analyze
	):
		mock_analyze.return_value = {
			"ats_score": 80,
			"strengths": ["Strong backend skills"]
		}

		with self.assertLogs("interviews.resume_context", level="INFO") as logs:
			get_resume_context(
				user=self.user,
				uploaded_file=self._make_upload()
			)

		self.assertTrue(
			any("interview_resume_cache_miss" in message for message in logs.output)
		)


from django.contrib.admin.sites import site
from .models import InterviewSession, InterviewSimulation, InterviewSimulationAnswer, Status, QuestionType
from .admin import InterviewSimulationAdmin, InterviewSimulationAnswerAdmin


class InterviewSimulationTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(
			username="test_sim_user",
			password="testpassword123"
		)
		self.session = InterviewSession.objects.create(
			user=self.user,
			role="Software Engineer",
			experience_level="junior",
			generated_questions={"hr_questions": [], "technical_questions": []}
		)

	def test_simulation_creation(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role="Software Engineer",
			experience_level="junior"
		)
		self.assertEqual(sim.user, self.user)
		self.assertEqual(sim.generated_set, self.session)
		self.assertEqual(sim.role, "Software Engineer")
		self.assertEqual(sim.experience_level, "junior")
		self.assertEqual(sim.score, 0)
		self.assertEqual(sim.status, Status.IN_PROGRESS)
		self.assertEqual(sim.ai_analysis, {})

	def test_answer_creation(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role="Software Engineer",
			experience_level="junior"
		)
		ans = InterviewSimulationAnswer.objects.create(
			simulation=sim,
			question_type=QuestionType.HR,
			question="Tell me about yourself.",
			answer="I am a developer.",
			ai_score=85,
			ai_feedback={"comments": "Good"},
			order=1
		)
		self.assertEqual(ans.simulation, sim)
		self.assertEqual(ans.question_type, QuestionType.HR)
		self.assertEqual(ans.question, "Tell me about yourself.")
		self.assertEqual(ans.answer, "I am a developer.")
		self.assertEqual(ans.ai_score, 85)
		self.assertEqual(ans.ai_feedback, {"comments": "Good"})
		self.assertEqual(ans.order, 1)

	def test_cascade_deletion_user(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			role="Software Engineer",
			experience_level="junior"
		)
		self.user.delete()
		self.assertFalse(InterviewSimulation.objects.filter(id=sim.id).exists())

	def test_cascade_deletion_simulation(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			role="Software Engineer",
			experience_level="junior"
		)
		ans = InterviewSimulationAnswer.objects.create(
			simulation=sim,
			question_type=QuestionType.TECHNICAL,
			question="What is a process?",
			order=1
		)
		sim.delete()
		self.assertFalse(InterviewSimulationAnswer.objects.filter(id=ans.id).exists())

	def test_set_null_deletion_question_set(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role="Software Engineer",
			experience_level="junior"
		)
		self.session.delete()
		sim.refresh_from_db()
		self.assertIsNone(sim.generated_set)

	def test_defaults(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			role="Software Engineer",
			experience_level="junior"
		)
		ans = InterviewSimulationAnswer.objects.create(
			simulation=sim,
			question_type=QuestionType.TECHNICAL,
			question="What is a process?",
			order=1
		)
		self.assertEqual(sim.status, Status.IN_PROGRESS)
		self.assertEqual(sim.ai_analysis, {})
		self.assertEqual(ans.ai_feedback, {})
		self.assertEqual(ans.answer, "")

	def test_str_methods(self):
		sim = InterviewSimulation.objects.create(
			user=self.user,
			role="Software Engineer",
			experience_level="junior"
		)
		ans = InterviewSimulationAnswer.objects.create(
			simulation=sim,
			question_type=QuestionType.TECHNICAL,
			question="What is a process?",
			order=2
		)
		self.assertEqual(str(sim), f"{self.user.username} - Software Engineer")
		self.assertEqual(str(ans), f"{sim.id} - Q2")

	def test_admin_registration(self):
		self.assertIn(InterviewSimulation, site._registry)
		self.assertIn(InterviewSimulationAnswer, site._registry)
		self.assertIsInstance(site._registry[InterviewSimulation], InterviewSimulationAdmin)
		self.assertIsInstance(site._registry[InterviewSimulationAnswer], InterviewSimulationAnswerAdmin)

	def test_user_can_create_simulation_and_metadata_redirect(self):
		self.client.force_login(self.user)
		response = self.client.post(f"/interviews/simulation/start/{self.session.id}/")
		self.assertEqual(response.status_code, 302)

		# Check simulation was created with correct metadata
		sim = InterviewSimulation.objects.first()
		self.assertIsNotNone(sim)
		self.assertEqual(sim.user, self.user)
		self.assertEqual(sim.generated_set, self.session)
		self.assertEqual(sim.role, self.session.role)
		self.assertEqual(sim.experience_level, self.session.experience_level)
		self.assertEqual(sim.status, Status.IN_PROGRESS)

		# Check redirect
		self.assertEqual(response.url, f"/interviews/simulation/{sim.id}/")

	def test_user_cannot_access_another_users_set(self):
		user_model = get_user_model()
		other_user = user_model.objects.create_user(
			username="other_user",
			password="password123"
		)
		self.client.force_login(other_user)
		response = self.client.post(f"/interviews/simulation/start/{self.session.id}/")
		self.assertEqual(response.status_code, 403)

	def test_existing_in_progress_simulation_is_resumed(self):
		self.client.force_login(self.user)
		# Create an existing IN_PROGRESS simulation
		existing_sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role=self.session.role,
			experience_level=self.session.experience_level,
			status=Status.IN_PROGRESS
		)

		with self.assertLogs("interviews.views", level="INFO") as logs:
			response = self.client.post(f"/interviews/simulation/start/{self.session.id}/")

		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.url, f"/interviews/simulation/{existing_sim.id}/")

		# Check resume log
		self.assertTrue(
			any("simulation_resumed" in message for message in logs.output)
		)

		# Check that no new simulation was created
		self.assertEqual(InterviewSimulation.objects.count(), 1)

	def test_completed_simulation_creates_new_attempt(self):
		self.client.force_login(self.user)
		# Create an existing COMPLETED simulation
		existing_sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role=self.session.role,
			experience_level=self.session.experience_level,
			status=Status.COMPLETED
		)

		response = self.client.post(f"/interviews/simulation/start/{self.session.id}/")
		self.assertEqual(response.status_code, 302)

		# Check that a new simulation was created
		self.assertEqual(InterviewSimulation.objects.count(), 2)
		new_sim = InterviewSimulation.objects.exclude(id=existing_sim.id).first()
		self.assertEqual(response.url, f"/interviews/simulation/{new_sim.id}/")

	def test_questions_copied_and_coding_excluded_and_ordering_preserved(self):
		self.client.force_login(self.user)

		# Set up a session with HR, Technical, and Coding questions
		self.session.generated_questions = {
			"hr_questions": ["HR Q1", "HR Q2"],
			"technical_questions": ["Tech Q1", "Tech Q2"],
			"coding_questions": ["Coding Q1"]
		}
		self.session.save()

		with self.assertLogs("interviews.views", level="INFO") as logs:
			response = self.client.post(f"/interviews/simulation/start/{self.session.id}/")

		self.assertEqual(response.status_code, 302)

		sim = InterviewSimulation.objects.first()
		answers = list(sim.answers.all().order_by("order"))

		# Check that 4 answers are created (2 HR + 2 Tech, coding excluded)
		self.assertEqual(len(answers), 4)

		# Check logs
		self.assertTrue(
			any("simulation_created" in message for message in logs.output)
		)
		self.assertTrue(
			any("simulation_question_count" in message for message in logs.output)
		)

		# Check ordering and correct values
		# HR questions first
		self.assertEqual(answers[0].question, "HR Q1")
		self.assertEqual(answers[0].question_type, QuestionType.HR)
		self.assertEqual(answers[0].order, 1)

		self.assertEqual(answers[1].question, "HR Q2")
		self.assertEqual(answers[1].question_type, QuestionType.HR)
		self.assertEqual(answers[1].order, 2)

		# Tech questions next
		self.assertEqual(answers[2].question, "Tech Q1")
		self.assertEqual(answers[2].question_type, QuestionType.TECHNICAL)
		self.assertEqual(answers[2].order, 3)

		self.assertEqual(answers[3].question, "Tech Q2")
		self.assertEqual(answers[3].question_type, QuestionType.TECHNICAL)
		self.assertEqual(answers[3].order, 4)


import json


class SimulationSessionViewTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(
			username="session_test_user",
			password="password123"
		)
		self.other_user = user_model.objects.create_user(
			username="other_session_user",
			password="password123"
		)
		self.session = InterviewSession.objects.create(
			user=self.user,
			role="Backend Engineer",
			experience_level="junior",
			generated_questions={
				"hr_questions": ["Tell me about yourself.", "Why this role?"],
				"technical_questions": ["What is REST?", "Explain caching."],
				"coding_questions": ["FizzBuzz"]
			}
		)
		self.sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role=self.session.role,
			experience_level=self.session.experience_level,
			status=Status.IN_PROGRESS,
		)
		# Create answers for the simulation
		self.answers = []
		for i, q in enumerate(["Tell me about yourself.", "Why this role?"], start=1):
			self.answers.append(InterviewSimulationAnswer.objects.create(
				simulation=self.sim,
				question_type=QuestionType.HR,
				question=q,
				answer="",
				order=i
			))
		for i, q in enumerate(["What is REST?", "Explain caching."], start=3):
			self.answers.append(InterviewSimulationAnswer.objects.create(
				simulation=self.sim,
				question_type=QuestionType.TECHNICAL,
				question=q,
				answer="",
				order=i
			))

	def _url(self):
		return f"/interviews/simulation/{self.sim.id}/"

	def _autosave_url(self):
		return f"/interviews/simulation/{self.sim.id}/autosave/"

	# 1. Simulation page loads for authenticated owner
	def test_simulation_page_loads(self):
		self.client.force_login(self.user)
		response = self.client.get(self._url())
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "AI Interview Simulator")
		self.assertContains(response, "Backend Engineer")

	# 2. User ownership — another user gets 403
	def test_user_ownership_forbidden(self):
		self.client.force_login(self.other_user)
		response = self.client.get(self._url())
		self.assertEqual(response.status_code, 403)

	# 3. Autosave endpoint returns success
	def test_autosave_works(self):
		self.client.force_login(self.user)
		ans = self.answers[0]
		payload = json.dumps({"answer_id": ans.id, "answer": "I am a backend developer."})
		response = self.client.post(
			self._autosave_url(),
			data=payload,
			content_type="application/json"
		)
		self.assertEqual(response.status_code, 200)
		data = json.loads(response.content)
		self.assertTrue(data["success"])

	# 4. Autosave updates the database
	def test_autosave_updates_db(self):
		self.client.force_login(self.user)
		ans = self.answers[0]
		payload = json.dumps({"answer_id": ans.id, "answer": "Updated answer text."})
		self.client.post(
			self._autosave_url(),
			data=payload,
			content_type="application/json"
		)
		ans.refresh_from_db()
		self.assertEqual(ans.answer, "Updated answer text.")

	# 5. Autosave forbidden for other users
	def test_autosave_forbidden_for_other_user(self):
		self.client.force_login(self.other_user)
		ans = self.answers[0]
		payload = json.dumps({"answer_id": ans.id, "answer": "Hacked."})
		response = self.client.post(
			self._autosave_url(),
			data=payload,
			content_type="application/json"
		)
		self.assertEqual(response.status_code, 403)
		ans.refresh_from_db()
		self.assertEqual(ans.answer, "")  # Unchanged

	# 6. Completed simulations cannot be edited via autosave
	def test_autosave_blocked_for_completed_simulation(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		ans = self.answers[0]
		payload = json.dumps({"answer_id": ans.id, "answer": "Late answer."})
		response = self.client.post(
			self._autosave_url(),
			data=payload,
			content_type="application/json"
		)
		self.assertEqual(response.status_code, 400)
		ans.refresh_from_db()
		self.assertEqual(ans.answer, "")  # Unchanged

	# 7. Completed simulation page redirects to results
	def test_completed_simulation_redirects(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.get(self._url())
		self.assertEqual(response.status_code, 302)
		self.assertIn("/results/", response.url)

	# 8. Progress calculation — answered vs total
	def test_progress_calculation(self):
		# Answer 2 out of 4 questions
		self.answers[0].answer = "My answer"
		self.answers[0].save()
		self.answers[1].answer = "Another answer"
		self.answers[1].save()

		self.client.force_login(self.user)
		response = self.client.get(self._url())
		self.assertContains(response, "2")
		self.assertContains(response, "4")

	# 9. Resume flow — saved answers reload on GET
	def test_saved_answers_reload(self):
		self.answers[0].answer = "Persisted answer"
		self.answers[0].save()

		self.client.force_login(self.user)
		response = self.client.get(self._url())
		self.assertEqual(response.status_code, 200)
		# The saved answer should appear in the JSON payload embedded in the page
		self.assertContains(response, "Persisted answer")

	# 10. Navigation rendering — HR and Technical sections appear
	def test_navigation_rendering(self):
		self.client.force_login(self.user)
		response = self.client.get(self._url())
		self.assertContains(response, "HR Questions")
		self.assertContains(response, "Technical Questions")

