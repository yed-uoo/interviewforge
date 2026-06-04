from django.contrib import admin
from .models import Topic, Subtopic, Question


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
