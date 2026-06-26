from django.contrib import admin
from .models import InterviewSimulation, InterviewSimulationAnswer


@admin.register(InterviewSimulation)
class InterviewSimulationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'role',
        'experience_level',
        'status',
        'score',
        'started_at',
        'submitted_at',
    )
    list_filter = (
        'status',
        'experience_level',
    )
    search_fields = (
        'user__username',
        'role',
    )
    readonly_fields = (
        'started_at',
        'submitted_at',
        'created_at',
        'updated_at',
    )


@admin.register(InterviewSimulationAnswer)
class InterviewSimulationAnswerAdmin(admin.ModelAdmin):
    list_display = (
        'simulation',
        'order',
        'question_type',
        'ai_score',
    )
    list_filter = (
        'question_type',
    )
    search_fields = (
        'question',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
    )
