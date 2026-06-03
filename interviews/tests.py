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
