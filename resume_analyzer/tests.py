from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from unittest.mock import patch

from .models import Resume
from .utils import compute_content_hash

class ResumeHashUtilsTests(TestCase):
	def test_same_normalized_text_produces_same_hash(self):
		hash_one = compute_content_hash("Hello   world")
		hash_two = compute_content_hash("Hello\nworld")
		self.assertEqual(hash_one, hash_two)

	def test_cache_version_changes_hash(self):
		with patch("resume_analyzer.utils.CACHE_VERSION", "v1"):
			hash_one = compute_content_hash("Hello world")

		with patch("resume_analyzer.utils.CACHE_VERSION", "v2"):
			hash_two = compute_content_hash("Hello world")

		self.assertNotEqual(hash_one, hash_two)


class ResumeAnalyzerCacheTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_user(
			username="tester",
			password="password123"
		)
		self.client.login(
			username="tester",
			password="password123"
		)

	def _make_upload(self):
		return SimpleUploadedFile(
			"resume.pdf",
			b"%PDF-1.4 test content",
			content_type="application/pdf"
		)

	@patch("resume_analyzer.views.analyze_resume")
	@patch("resume_analyzer.views.validate_resume_document", return_value=True)
	@patch("resume_analyzer.views.extract_text_from_pdf", return_value="Hello resume")
	def test_cache_miss_calls_analyze_resume(
		self,
		mock_extract_text,
		mock_validate,
		mock_analyze
	):
		mock_analyze.return_value = {
			"ats_score": 78,
			"strengths": ["Strong backend skills"]
		}

		response = self.client.post(
			reverse("upload_resume"),
			{"file": self._make_upload()}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(mock_analyze.call_count, 1)
		self.assertEqual(Resume.objects.count(), 1)

		resume = Resume.objects.first()
		self.assertEqual(resume.ats_score, 78)
		self.assertEqual(
			resume.analysis_data,
			mock_analyze.return_value
		)
		self.assertEqual(
			resume.content_hash,
			compute_content_hash("Hello resume")
		)

	@patch("resume_analyzer.views.analyze_resume")
	@patch("resume_analyzer.views.validate_resume_document", return_value=True)
	@patch("resume_analyzer.views.extract_text_from_pdf", return_value="Hello resume")
	def test_cache_hit_reuses_analysis_and_skips_analyze_resume(
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
			ats_score=91,
			analysis_data={"ats_score": 91, "strengths": ["Cached"]},
			content_hash=content_hash
		)

		response = self.client.post(
			reverse("upload_resume"),
			{"file": self._make_upload()}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(mock_analyze.call_count, 0)
		self.assertEqual(Resume.objects.count(), 2)

		new_resume = Resume.objects.order_by("-id").first()
		self.assertEqual(new_resume.ats_score, cached_resume.ats_score)
		self.assertEqual(new_resume.analysis_data, cached_resume.analysis_data)
		self.assertEqual(new_resume.content_hash, cached_resume.content_hash)

	@patch("resume_analyzer.views.analyze_resume")
	@patch("resume_analyzer.views.validate_resume_document", return_value=True)
	@patch("resume_analyzer.views.extract_text_from_pdf", return_value="Hello resume")
	def test_cache_miss_logs_event(
		self,
		mock_extract_text,
		mock_validate,
		mock_analyze
	):
		mock_analyze.return_value = {
			"ats_score": 78,
			"strengths": ["Strong backend skills"]
		}

		with self.assertLogs("resume_analyzer.views", level="INFO") as logs:
			self.client.post(
				reverse("upload_resume"),
				{"file": self._make_upload()}
			)

		self.assertTrue(
			any("resume_cache_miss" in message for message in logs.output)
		)

	@patch("resume_analyzer.views.analyze_resume")
	@patch("resume_analyzer.views.validate_resume_document", return_value=True)
	@patch("resume_analyzer.views.extract_text_from_pdf", return_value="Hello resume")
	def test_cache_hit_logs_event(
		self,
		mock_extract_text,
		mock_validate,
		mock_analyze
	):
		content_hash = compute_content_hash("Hello resume")
		Resume.objects.create(
			user=self.user,
			file=self._make_upload(),
			extracted_text="Hello resume",
			ats_score=91,
			analysis_data={"ats_score": 91, "strengths": ["Cached"]},
			content_hash=content_hash
		)

		with self.assertLogs("resume_analyzer.views", level="INFO") as logs:
			self.client.post(
				reverse("upload_resume"),
				{"file": self._make_upload()}
			)

		self.assertTrue(
			any("resume_cache_hit" in message for message in logs.output)
		)
