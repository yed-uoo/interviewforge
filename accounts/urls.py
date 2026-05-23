from django.urls import path
from django.contrib.auth import views as auth_views
from .views import signup_view, profile_view, logout_view, dashboard_view 

urlpatterns = [
    path('signup/', signup_view, name='signup'),

    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='accounts/login.html'
        ),
        name='login'
    ),

    path('logout/', logout_view, name='logout'),
    path('profile/', profile_view, name='profile'),
    path('dashboard/', dashboard_view, name='dashboard'),
]