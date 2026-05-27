from django.db import models
from django.conf import settings
from resume_analyzer.models import Resume


class InterviewSession(models.Model):
    EXPERIENCE_CHOICES = [
        ('fresher', 'Fresher'),
        ('junior', 'Junior'),
        ('mid', 'Mid-Level'),
        ('senior', 'Senior'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    resume = models.ForeignKey(
        Resume,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    role = models.CharField(
        max_length=150
    )

    experience_level = models.CharField(
        max_length=20,
        choices=EXPERIENCE_CHOICES
    )

    job_description = models.TextField(
        blank=True
    )

    generated_questions = models.JSONField()

    used_resume_context = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.role}"