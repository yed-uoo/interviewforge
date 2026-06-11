# pyrefly: ignore [missing-import]
from django.contrib import admin
from .models import Topic, Subtopic, Question, MCQTest, MCQTestQuestion, MCQAnswer


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Subtopic)
class SubtopicAdmin(admin.ModelAdmin):
    list_display = ("name", "topic")
    list_filter = ("topic",)
    search_fields = ("name", "topic__name")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("question_preview", "topic", "subtopic", "difficulty", "correct_option")
    list_filter = ("difficulty", "topic", "subtopic")
    search_fields = ("question",)

    @admin.display(description="Question")
    def question_preview(self, obj):
        return obj.question[:80]


@admin.register(MCQTest)
class MCQTestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "topic",
        "total_questions",
        "score",
        "percentage",
        "status",
        "created_at",
        "submitted_at",
    )
    list_filter = ("topic", "status", "created_at")
    search_fields = ("user__username", "user__email", "topic__name")
    readonly_fields = ("created_at", "submitted_at")


@admin.register(MCQTestQuestion)
class MCQTestQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "test", "question_preview", "order")
    list_filter = ("test__topic", "test__status", "test__created_at")
    search_fields = ("question__question", "test__user__username", "test__user__email")

    @admin.display(description="Question")
    def question_preview(self, obj):
        return obj.question.question[:80]


@admin.register(MCQAnswer)
class MCQAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "test",
        "question_preview",
        "selected_option",
        "is_correct",
        "answered_at",
    )
    list_filter = ("test__topic", "test__status", "is_correct", "answered_at")
    search_fields = ("question__question", "test__user__username", "test__user__email")

    @admin.display(description="Question")
    def question_preview(self, obj):
        return obj.question.question[:80]
