from django.urls import path
from .views import setup_test_view, test_session_view, test_results_view, test_history_view

urlpatterns = [
    path('setup/', setup_test_view, name='mcq_setup'),
    path('history/', test_history_view, name='mcq_history'),
    path('test/<int:test_id>/', test_session_view, name='mcq_test_session'),
    path('test/<int:test_id>/results/', test_results_view, name='mcq_results'),
]
