from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from .forms import SignupForm


def signup_view(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('profile')

    else:
        form = SignupForm()

    return render(
        request,
        'accounts/signup.html',
        {'form': form}
    )


@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html')


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard_view(request):
    from resume_analyzer.models import Resume
    from interviews.models import InterviewSimulation, Status
    from mcq_engine.models import MCQTest

    resume_analyses = Resume.objects.filter(user=request.user).count()
    interview_simulations = InterviewSimulation.objects.filter(user=request.user).count()
    completed_interviews = InterviewSimulation.objects.filter(
        user=request.user, status=Status.COMPLETED
    ).count()
    mcq_tests_taken = MCQTest.objects.filter(user=request.user).count()

    has_activity = any([resume_analyses, interview_simulations, mcq_tests_taken])

    return render(request, 'accounts/dashboard.html', {
        'resume_analyses': resume_analyses,
        'interview_simulations': interview_simulations,
        'completed_interviews': completed_interviews,
        'mcq_tests_taken': mcq_tests_taken,
        'has_activity': has_activity,
    })