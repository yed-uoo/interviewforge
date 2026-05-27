from django.db import models
from django.conf import settings
import os


class Resume(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    file = models.FileField(
        upload_to='resumes/'
    )

    extracted_text = models.TextField(
        blank=True
    )

    ats_score = models.IntegerField(
        default=0
    )

    analysis_data = models.JSONField(
        default=dict,
        blank=True
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return os.path.basename(self.file.name)