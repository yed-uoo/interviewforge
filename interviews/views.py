from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import InterviewGeneratorForm
from .ai_generator import generate_interview_questions
from .resume_context import get_resume_context
from .models import InterviewSession

@login_required
def interview_history(request):
    sessions = InterviewSession.objects.filter(
        user=request.user
    ).order_by('-created_at')

    return render(
        request,
        'interviews/history.html',
        {
            'sessions': sessions
        }
    )


@login_required
def interview_detail(request, session_id):
    session = get_object_or_404(
        InterviewSession,
        id=session_id,
        user=request.user
    )

    return render(
        request,
        'interviews/detail.html',
        {
            'session': session
        }
    )

@login_required
def generate_interview(request):
    if request.method == 'POST':
        form = InterviewGeneratorForm(
            request.POST,
            request.FILES,
            user=request.user
        )

        if form.is_valid():
            role = form.cleaned_data['role']
            experience_level = form.cleaned_data['experience_level']
            job_description = form.cleaned_data['job_description']
            existing_resume = form.cleaned_data['existing_resume']
            uploaded_resume = form.cleaned_data['resume_file']

            try:
                resume_context = get_resume_context(
                    user=request.user,
                    existing_resume=existing_resume,
                    uploaded_file=uploaded_resume
                )

                questions = generate_interview_questions(
                    role=role,
                    experience_level=experience_level,
                    job_description=job_description,
                    resume_text=resume_context['resume_text'],
                    used_resume_context=resume_context['used_resume_context']
                )

                session = InterviewSession.objects.create(
                    user=request.user,
                    resume=resume_context['resume'],
                    role=role,
                    experience_level=experience_level,
                    job_description=job_description,
                    generated_questions=questions,
                    used_resume_context=resume_context['used_resume_context']
                )

                return render(
                    request,
                    'interviews/result.html',
                    {
                        'questions': questions,
                        'role': role,
                        'experience_level': experience_level,
                        'session': session,
                        'used_resume_context': resume_context['used_resume_context']
                    }
                )

            except Exception as e:
                return render(
                    request,
                    'interviews/generate.html',
                    {
                        'form': form,
                        'error': str(e)
                    }
                )

    else:
        form = InterviewGeneratorForm(
            user=request.user
        )

    return render(
        request,
        'interviews/generate.html',
        {
            'form': form
        }
    )