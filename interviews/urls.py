from django.urls import path
from .views import (
    generate_interview,
    interview_history,
    interview_detail
)


urlpatterns = [
    path(
        'generate/',
        generate_interview,
        name='generate_interview'
    ),

    path(
        'history/',
        interview_history,
        name='interview_history'
    ),

    path(
        'history/<int:session_id>/',
        interview_detail,
        name='interview_detail'
    ),
]