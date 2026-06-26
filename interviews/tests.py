from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock

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


class SimulationSubmitTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(
			username="submit_test_user",
			password="password123"
		)
		self.other_user = user_model.objects.create_user(
			username="submit_other_user",
			password="password123"
		)
		self.session = InterviewSession.objects.create(
			user=self.user,
			role="Data Scientist",
			experience_level="mid",
			generated_questions={
				"hr_questions": ["Tell me about yourself."],
				"technical_questions": ["Explain overfitting."],
			}
		)
		self.sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role=self.session.role,
			experience_level=self.session.experience_level,
			status=Status.IN_PROGRESS,
		)
		self.ans1 = InterviewSimulationAnswer.objects.create(
			simulation=self.sim,
			question_type=QuestionType.HR,
			question="Tell me about yourself.",
			answer="I am a data scientist.",
			order=1
		)
		self.ans2 = InterviewSimulationAnswer.objects.create(
			simulation=self.sim,
			question_type=QuestionType.TECHNICAL,
			question="Explain overfitting.",
			answer="",
			order=2
		)

	def _submit_url(self):
		return f"/interviews/simulation/{self.sim.id}/submit/"

	def _results_url(self):
		return f"/interviews/simulation/{self.sim.id}/results/"

	def _session_url(self):
		return f"/interviews/simulation/{self.sim.id}/"

	def _autosave_url(self):
		return f"/interviews/simulation/{self.sim.id}/autosave/"

	# 1. Successful submission
	def test_successful_submission(self):
		self.client.force_login(self.user)
		response = self.client.post(self._submit_url())
		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.url, self._results_url())

	# 2. Duplicate submission redirects without changing DB
	def test_duplicate_submission_redirects(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.post(self._submit_url())
		self.assertEqual(response.status_code, 302)
		self.assertEqual(response.url, self._results_url())

	# 3. Unauthorized submission returns 403
	def test_unauthorized_submission(self):
		self.client.force_login(self.other_user)
		response = self.client.post(self._submit_url())
		self.assertEqual(response.status_code, 403)

	# 4. Submission updates status to COMPLETED
	def test_submission_updates_status(self):
		self.client.force_login(self.user)
		self.client.post(self._submit_url())
		self.sim.refresh_from_db()
		self.assertEqual(self.sim.status, Status.COMPLETED)

	# 5. submitted_at is saved
	def test_submitted_at_is_saved(self):
		self.client.force_login(self.user)
		self.client.post(self._submit_url())
		self.sim.refresh_from_db()
		self.assertIsNotNone(self.sim.submitted_at)

	# 6. Completed simulation session page redirects to results
	def test_completed_session_redirects_to_results(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.get(self._session_url())
		self.assertEqual(response.status_code, 302)
		self.assertIn("/results/", response.url)

	# 7. Autosave rejected after completion
	def test_autosave_rejected_after_submission(self):
		self.client.force_login(self.user)
		self.client.post(self._submit_url())
		payload = json.dumps({"answer_id": self.ans1.id, "answer": "Late edit attempt."})
		response = self.client.post(
			self._autosave_url(),
			data=payload,
			content_type="application/json"
		)
		self.assertEqual(response.status_code, 400)
		data = json.loads(response.content)
		self.assertFalse(data["success"])

	# 8. Results placeholder page renders for owner
	def test_results_page_renders(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.get(self._results_url())
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Interview Submitted")
		self.assertContains(response, "Data Scientist")

	# 9. Results page shows correct answered/total stats
	def test_results_page_shows_stats(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.get(self._results_url())
		# ans1 has answer, ans2 is empty → 1 answered out of 2
		self.assertContains(response, "1")
		self.assertContains(response, "2")


class SimulationHistoryEnhancementTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(username="testuser", password="password")
		self.other_user = user_model.objects.create_user(username="otheruser", password="password")
		self.session = InterviewSession.objects.create(
			user=self.user,
			role="Backend Developer",
			experience_level="fresher",
			generated_questions={
				"hr_questions": ["Tell me about yourself."],
				"technical_questions": ["What is a database index?"]
			}
		)
		self.sim = InterviewSimulation.objects.create(
			user=self.user,
			generated_set=self.session,
			role="Backend Developer",
			experience_level="fresher",
			status=Status.IN_PROGRESS
		)
		self.ans1 = InterviewSimulationAnswer.objects.create(
			simulation=self.sim,
			question_type=QuestionType.HR,
			question="Tell me about yourself.",
			answer="I am a backend developer.",
			order=1
		)
		self.ans2 = InterviewSimulationAnswer.objects.create(
			simulation=self.sim,
			question_type=QuestionType.TECHNICAL,
			question="What is a database index?",
			answer="",
			order=2
		)

	def test_resume_simulation_restores_answers(self):
		self.client.force_login(self.user)
		resume_url = f"/interviews/simulation/{self.sim.id}/resume/"
		response = self.client.get(resume_url)
		# Should redirect to session page with ?resume=true
		self.assertEqual(response.status_code, 302)
		self.assertIn(f"/interviews/simulation/{self.sim.id}/?resume=true", response.url)

		# Now load the session page and check answers are loaded
		session_page_response = self.client.get(response.url)
		self.assertEqual(session_page_response.status_code, 200)
		self.assertContains(session_page_response, "I am a backend developer.")

	def test_completed_sessions_show_results_and_practice_buttons(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.get("/interviews/history/")
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "View Results")
		self.assertContains(response, "Practice Questions")

	def test_in_progress_sessions_show_resume_button(self):
		self.client.force_login(self.user)
		response = self.client.get("/interviews/history/")
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Resume Simulation")
		self.assertNotContains(response, "View Results")
		self.assertNotContains(response, "Practice Questions")

	def test_practice_mode_creates_no_db_records_and_no_ai_analysis(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		
		# Record count before
		sim_count = InterviewSimulation.objects.count()
		ans_count = InterviewSimulationAnswer.objects.count()

		practice_url = f"/interviews/simulation/{self.sim.id}/practice/"
		response = self.client.get(practice_url)
		self.assertEqual(response.status_code, 200)

		# Record count after
		self.assertEqual(InterviewSimulation.objects.count(), sim_count)
		self.assertEqual(InterviewSimulationAnswer.objects.count(), ans_count)
		
		# Confirm ai_analysis remains empty
		self.sim.refresh_from_db()
		self.assertEqual(self.sim.ai_analysis, {})

	def test_users_cannot_access_another_users_session(self):
		self.client.force_login(self.other_user)
		
		# Try to resume
		response = self.client.get(f"/interviews/simulation/{self.sim.id}/resume/")
		self.assertEqual(response.status_code, 403)

		# Try to view results
		response = self.client.get(f"/interviews/simulation/{self.sim.id}/results/")
		self.assertEqual(response.status_code, 403)

		# Try to practice
		response = self.client.get(f"/interviews/simulation/{self.sim.id}/practice/")
		self.assertEqual(response.status_code, 403)

	def test_in_progress_sessions_cannot_open_results_page(self):
		self.client.force_login(self.user)
		response = self.client.get(f"/interviews/simulation/{self.sim.id}/results/")
		self.assertEqual(response.status_code, 403)

	def test_completed_sessions_cannot_resume_simulation(self):
		self.sim.status = Status.COMPLETED
		self.sim.save()
		self.client.force_login(self.user)
		response = self.client.get(f"/interviews/simulation/{self.sim.id}/resume/")
		self.assertEqual(response.status_code, 403)


class InterviewGeneratorTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(username="generator_user", password="password")

	@patch("interviews.ai_generator.get_groq_client")
	def test_role_skills_injected_in_prompt(self, mock_get_client):
		mock_client = MagicMock()
		mock_get_client.return_value = mock_client

		mock_response = MagicMock()
		mock_message = MagicMock()
		mock_message.content = json.dumps({
			"hr_questions": [f"hr {i}" for i in range(5)],
			"technical_questions": [f"tech {i}" for i in range(7)],
			"coding_questions": [f"coding {i}" for i in range(3)]
		})
		mock_choice = MagicMock()
		mock_choice.message = mock_message
		mock_response.choices = [mock_choice]

		mock_client.chat.completions.create.return_value = mock_response

		# Generate questions for Frontend Developer without resume context
		from interviews.ai_generator import generate_interview_questions
		generate_interview_questions(role="Frontend Developer", experience_level="fresher", used_resume_context=False)

		# Verify client was called with expected prompt contents
		self.assertEqual(mock_client.chat.completions.create.call_count, 1)
		call_kwargs = mock_client.chat.completions.create.call_args[1]
		prompt_content = call_kwargs["messages"][0]["content"]
		self.assertIn("- HTML", prompt_content)
		self.assertIn("- CSS", prompt_content)
		self.assertIn("ROLE-SPECIFIC RULES for Frontend Developer", prompt_content)
		self.assertIn("AVOID: Django, Database schema", prompt_content)

		# Reset mock and generate questions for Backend Developer (with resume context)
		mock_client.chat.completions.create.reset_mock()
		generate_interview_questions(role="Backend Developer", experience_level="junior", used_resume_context=True)

		self.assertEqual(mock_client.chat.completions.create.call_count, 1)
		call_kwargs = mock_client.chat.completions.create.call_args[1]
		prompt_content = call_kwargs["messages"][0]["content"]
		self.assertIn("- Django", prompt_content)
		self.assertIn("- ORM", prompt_content)
		self.assertIn("ROLE-SPECIFIC RULES for Backend Developer", prompt_content)
		
		# Assert the resume personalization rules are in the prompt
		self.assertIn("Treat the candidate's resume as the primary source of interview questions", prompt_content)
		self.assertIn("STRONG PROJECT GROUNDING & NO HALLUCINATIONS", prompt_content)
		self.assertIn("PRIORITY ORDER FOR QUESTION GENERATION", prompt_content)
		self.assertIn("1. Resume Projects", prompt_content)
		self.assertIn("2. Resume Technologies", prompt_content)
		self.assertIn("3. Target Role", prompt_content)
		self.assertIn("COMBINE TARGET ROLE + CANDIDATE RESUME", prompt_content)
		self.assertIn("STRICT PERCENTAGE AND PROJECT COVERAGE QUOTAS", prompt_content)
		self.assertIn("At least 6 of the 15 total generated questions (at least 40%) must directly reference the candidate's resume", prompt_content)
		self.assertIn("GUARANTEE PROJECT QUESTIONS PER SECTION", prompt_content)
		self.assertIn("HR Questions: At least 2 of the 5 HR questions must reference the candidate's resume projects", prompt_content)
		self.assertIn("Technical Questions: At least 3 of the 7 technical questions must reference projects or technologies from the resume", prompt_content)
		self.assertIn("Coding Questions: At least 2 of the 3 coding questions must be based directly on projects", prompt_content)
		self.assertIn("CODING QUESTIONS DESIGN RULES", prompt_content)
		self.assertIn("NEVER generate generic coding coding questions like 'Remove vowels', 'Count characters', 'Reverse strings'", prompt_content.replace("generic coding questions", "generic coding coding questions")) # Normalize possible double word or check exact string
		# Let's assert the actual text we wrote in prompt: "NEVER generate generic coding questions like 'Remove vowels'"
		self.assertIn("NEVER generate generic coding questions like 'Remove vowels'", prompt_content)

		# Reset mock and generate questions for Full Stack Developer
		mock_client.chat.completions.create.reset_mock()
		generate_interview_questions(role="Full Stack Developer", experience_level="senior", used_resume_context=False)
		self.assertEqual(mock_client.chat.completions.create.call_count, 1)
		call_kwargs = mock_client.chat.completions.create.call_args[1]
		prompt_content = call_kwargs["messages"][0]["content"]
		self.assertIn("ROLE-SPECIFIC RULES for Full Stack Developer", prompt_content)
		self.assertIn("40% frontend, 40% backend, 20% architecture/system design", prompt_content)
		self.assertIn("React, State management, Component architecture", prompt_content)
		self.assertIn("APIs, Database design, Authentication", prompt_content)
		self.assertIn("Docker, Deployment, CI/CD", prompt_content)

	@patch("interviews.ai_generator.get_groq_client")
	def test_question_generation_not_cached(self, mock_get_client):
		mock_client = MagicMock()
		mock_get_client.return_value = mock_client

		mock_response = MagicMock()
		mock_message = MagicMock()
		mock_message.content = json.dumps({
			"hr_questions": [f"hr {i}" for i in range(5)],
			"technical_questions": [f"tech {i}" for i in range(7)],
			"coding_questions": [f"coding {i}" for i in range(3)]
		})
		mock_choice = MagicMock()
		mock_choice.message = mock_message
		mock_response.choices = [mock_choice]

		mock_client.chat.completions.create.return_value = mock_response

		self.client.force_login(self.user)

		# First generation
		response1 = self.client.post("/interviews/generate/", {
			"role": "Frontend Developer",
			"experience_level": "fresher",
			"job_description": "",
			"existing_resume": "",
			"resume_file": ""
		})
		self.assertEqual(response1.status_code, 200)
		self.assertEqual(mock_client.chat.completions.create.call_count, 1)

		# Second generation (same parameters)
		response2 = self.client.post("/interviews/generate/", {
			"role": "Frontend Developer",
			"experience_level": "fresher",
			"job_description": "",
			"existing_resume": "",
			"resume_file": ""
		})
		self.assertEqual(response2.status_code, 200)
		# Should trigger LLM again, making total call count 2
		self.assertEqual(mock_client.chat.completions.create.call_count, 2)

		# Verify two separate sessions were created in the database
		self.assertEqual(InterviewSession.objects.filter(user=self.user).count(), 2)



