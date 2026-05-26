from django.urls import path
from .views import upload_resume, analysis_history,view_analysis_report

urlpatterns = [
    path('upload/', upload_resume, name='upload_resume'),
    path('history/', analysis_history, name='analysis_history'),
    path(
        'report/<int:resume_id>/',
        view_analysis_report,
        name='view_analysis_report'
    ),
]