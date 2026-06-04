from django.db import models


class Topic(models.Model):
    name = models.CharField(max_length=200, verbose_name="Topic Name")

    class Meta:
        verbose_name = "Topic"
        verbose_name_plural = "Topics"

    def __str__(self):
        return self.name


class Subtopic(models.Model):
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="subtopics",
        verbose_name="Topic",
    )
    name = models.CharField(max_length=200, verbose_name="Subtopic Name")

    class Meta:
        verbose_name = "Subtopic"
        verbose_name_plural = "Subtopics"

    def __str__(self):
        return f"{self.topic.name} → {self.name}"


class Question(models.Model):

    class Difficulty(models.TextChoices):
        EASY   = "easy",   "Easy"
        MEDIUM = "medium", "Medium"
        HARD   = "hard",   "Hard"

    class CorrectOption(models.TextChoices):
        A = "A", "A"
        B = "B", "B"
        C = "C", "C"
        D = "D", "D"

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="Topic",
    )
    subtopic = models.ForeignKey(
        Subtopic,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="Subtopic",
    )
    difficulty = models.CharField(
        max_length=10,
        choices=Difficulty.choices,
        verbose_name="Difficulty",
    )
    question = models.TextField(verbose_name="Question")
    option_a = models.CharField(max_length=500, verbose_name="Option A")
    option_b = models.CharField(max_length=500, verbose_name="Option B")
    option_c = models.CharField(max_length=500, verbose_name="Option C")
    option_d = models.CharField(max_length=500, verbose_name="Option D")
    correct_option = models.CharField(
        max_length=1,
        choices=CorrectOption.choices,
        verbose_name="Correct Option",
    )
    explanation = models.TextField(
        blank=True,
        null=True,
        verbose_name="Explanation",
        help_text="Optional rationale explaining why the correct option is right.",
    )

    class Meta:
        verbose_name = "Question"
        verbose_name_plural = "Questions"

    def __str__(self):
        return f"[{self.get_difficulty_display()}] {self.question[:60]}"
