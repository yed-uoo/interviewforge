from django.urls import path
from .views import (
    generate_interview,
    interview_history,
    interview_detail,
    start_simulation_view,
    simulation_session_view,
    simulation_autosave_view,
    submit_simulation_view,
    simulation_results_view,
    resume_simulation_view,
    practice_questions_view,
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

    path(
        'simulation/start/<int:set_id>/',
        start_simulation_view,
        name='start_simulation',
    ),

    path(
        'simulation/<int:simulation_id>/',
        simulation_session_view,
        name='simulation_session',
    ),

    path(
        'simulation/<int:simulation_id>/autosave/',
        simulation_autosave_view,
        name='simulation_autosave',
    ),

    path(
        'simulation/<int:simulation_id>/submit/',
        submit_simulation_view,
        name='submit_simulation',
    ),

    path(
        'simulation/<int:simulation_id>/results/',
        simulation_results_view,
        name='simulation_results',
    ),

    path(
        'simulation/<int:simulation_id>/resume/',
        resume_simulation_view,
        name='resume_simulation',
    ),

    path(
        'simulation/<int:simulation_id>/practice/',
        practice_questions_view,
        name='practice_questions',
    ),
]