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


class Status(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    COMPLETED = "COMPLETED", "Completed"


class QuestionType(models.TextChoices):
    HR = "HR", "HR"
    TECHNICAL = "TECHNICAL", "Technical"


class AnalysisStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class InterviewSimulation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="interview_simulations"
    )
    generated_set = models.ForeignKey(
        InterviewSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="simulations"
    )
    role = models.CharField(max_length=200)
    experience_level = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS
    )

    # ── Structured metric columns (frequently queried / rendered) ──────────
    score = models.PositiveIntegerField(default=0)          # kept for compat
    overall_score = models.PositiveIntegerField(default=0)
    communication_score = models.PositiveIntegerField(default=0)
    technical_score = models.PositiveIntegerField(default=0)
    confidence_score = models.PositiveIntegerField(default=0)
    clarity_score = models.PositiveIntegerField(default=0)
    problem_solving_score = models.PositiveIntegerField(default=0)
    readiness_score = models.PositiveIntegerField(default=0)
    answer_completion_score = models.PositiveIntegerField(default=0)

    # ── Async analysis state machine ───────────────────────────────────────
    analysis_status = models.CharField(
        max_length=20,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING,
    )

    # ── Flexible AI insights blob (strengths, weaknesses, improvement_plan,
    #    recommended_topics, resume_gap_analysis, per_question_analysis) ───
    ai_analysis = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class InterviewSimulationAnswer(models.Model):
    simulation = models.ForeignKey(
        InterviewSimulation,
        on_delete=models.CASCADE,
        related_name="answers"
    )
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices
    )
    question = models.TextField()
    answer = models.TextField(blank=True)

    # ── Legacy fields (kept for compatibility) ─────────────────────────────
    ai_score = models.PositiveIntegerField(default=0)
    ai_feedback = models.JSONField(default=dict, blank=True)

    # ── Per-question analytics (stored as columns for efficient rendering) ─
    score = models.PositiveIntegerField(default=0)
    feedback = models.TextField(blank=True)
    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    improved_answer = models.TextField(blank=True)

    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.simulation_id} - Q{self.order}"