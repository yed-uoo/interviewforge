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


import logging
from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from .models import InterviewSimulation, InterviewSimulationAnswer, Status, QuestionType

logger = logging.getLogger(__name__)

@login_required
def start_simulation_view(request, set_id):
    question_set = get_object_or_404(InterviewSession, id=set_id)

    if question_set.user != request.user:
        return HttpResponseForbidden("You do not own this question set.")

    in_progress_sim = InterviewSimulation.objects.filter(
        generated_set=question_set,
        status=Status.IN_PROGRESS
    ).first()

    if in_progress_sim:
        logger.info(f"simulation_resumed: Resumed in-progress simulation with ID {in_progress_sim.id}")
        return redirect(f"/interviews/simulation/{in_progress_sim.id}/")

    sim = InterviewSimulation.objects.create(
        user=request.user,
        generated_set=question_set,
        role=question_set.role,
        experience_level=question_set.experience_level,
        status=Status.IN_PROGRESS,
    )
    logger.info(f"simulation_created: Created simulation with ID {sim.id}")

    questions = question_set.generated_questions or {}
    hr_qs = questions.get("hr_questions", [])
    tech_qs = questions.get("technical_questions", [])

    answers_to_create = []
    order = 1
    for q in hr_qs:
        answers_to_create.append(
            InterviewSimulationAnswer(
                simulation=sim,
                question_type=QuestionType.HR,
                question=q,
                answer="",
                order=order
            )
        )
        order += 1

    for q in tech_qs:
        answers_to_create.append(
            InterviewSimulationAnswer(
                simulation=sim,
                question_type=QuestionType.TECHNICAL,
                question=q,
                answer="",
                order=order
            )
        )
        order += 1

    if answers_to_create:
        InterviewSimulationAnswer.objects.bulk_create(answers_to_create)

    logger.info(f"simulation_question_count: Simulation with ID {sim.id} populated with {len(answers_to_create)} questions")

    return redirect(f"/interviews/simulation/{sim.id}/")


import json
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone


@login_required
def simulation_session_view(request, simulation_id):
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return HttpResponseForbidden("You do not own this simulation.")

    if simulation.status == Status.COMPLETED:
        return redirect(f"/interviews/simulation/{simulation_id}/results/")

    answers = list(simulation.answers.all().order_by("order"))
    total_questions = len(answers)
    completed_count = sum(1 for a in answers if a.answer.strip())

    # Build safe JSON payload for JS consumption
    answers_json = {
        "simulationId": simulation.id,
        "autosaveUrl": f"/interviews/simulation/{simulation_id}/autosave/",
        "totalQuestions": total_questions,
        "answers": [
            {
                "id": a.id,
                "order": a.order,
                "questionType": a.question_type,
                "question": a.question,
                "savedAnswer": a.answer,
            }
            for a in answers
        ],
    }

    return render(request, "interviews/simulation_session.html", {
        "simulation": simulation,
        "answers": answers,
        "total_questions": total_questions,
        "completed_count": completed_count,
        "answers_json": answers_json,
    })


@login_required
@require_POST
def simulation_autosave_view(request, simulation_id):
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return JsonResponse({"success": False, "error": "Forbidden"}, status=403)

    if simulation.status == Status.COMPLETED:
        return JsonResponse({"success": False, "error": "Simulation already completed."}, status=400)

    try:
        data = json.loads(request.body)
        answer_id = data.get("answer_id")
        answer_text = data.get("answer", "")
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"success": False, "error": "Invalid request."}, status=400)

    answer = get_object_or_404(InterviewSimulationAnswer, id=answer_id, simulation=simulation)
    answer.answer = answer_text
    answer.save(update_fields=["answer", "updated_at"])

    return JsonResponse({"success": True})