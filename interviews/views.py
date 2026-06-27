from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import InterviewGeneratorForm
from .ai_generator import generate_interview_questions
from .resume_context import get_resume_context
from .models import InterviewSession

@login_required
def interview_history(request):
    simulations = InterviewSimulation.objects.filter(
        user=request.user
    ).select_related('generated_set__resume').prefetch_related('answers').order_by('-created_at')

    for sim in simulations:
        answers = list(sim.answers.all())
        sim.total_questions = len(answers)
        sim.answered_questions = sum(1 for a in answers if a.answer.strip())

        if sim.total_questions > 0:
            sim.progress_percentage = round((sim.answered_questions / sim.total_questions) * 100)
        else:
            sim.progress_percentage = 0

        # Temporary debugging to verify simulation lifecycle status
        logger.info(
            f"Simulation {sim.id} - {sim.role} - {sim.status}"
        )

        # State determination
        if sim.status.upper() == "COMPLETED":
            sim.state = "completed"
            sim.display_state = "completed"
        elif sim.answered_questions > 0:
            sim.state = "in_progress"
            sim.display_state = "in_progress"
        else:
            sim.state = "not_started"
            sim.display_state = "not_started"

    logger.info(
        f"History simulations: "
        f"{list(simulations.values('id','role','status'))}"
    )

    return render(
        request,
        'interviews/history.html',
        {
            'simulations': simulations
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

                # Pre-create simulation and its answers in GENERATED state immediately
                sim = InterviewSimulation.objects.create(
                    user=request.user,
                    generated_set=session,
                    role=role,
                    experience_level=experience_level,
                    status=Status.GENERATED,
                )
                logger.info(
                    f"Created simulation: id={sim.id}, role={sim.role}, status={sim.status}"
                )

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
from .models import InterviewSimulation, InterviewSimulationAnswer, Status, QuestionType, AnalysisStatus
from .ai_evaluator import run_evaluation_in_background, score_label, readiness_label

logger = logging.getLogger(__name__)

@login_required
def start_simulation_view(request, set_id):
    question_set = get_object_or_404(InterviewSession, id=set_id)

    if question_set.user != request.user:
        return HttpResponseForbidden("You do not own this question set.")

    # Check if a simulation already exists for this question set
    sim = InterviewSimulation.objects.filter(
        generated_set=question_set
    ).exclude(status=Status.COMPLETED).first()

    if sim:
        # If the simulation was newly generated, mark it in_progress
        if sim.status == Status.GENERATED:
            sim.status = Status.IN_PROGRESS
            sim.save(update_fields=["status"])
            logger.info(f"simulation_started: Started simulation with ID {sim.id} (formerly GENERATED)")
        else:
            logger.info(f"simulation_resumed: Resumed simulation with ID {sim.id} (status: {sim.status})")
        return redirect(f"/interviews/simulation/{sim.id}/")

    # Backwards compatibility for legacy sessions
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

    if simulation.status == Status.COMPLETED or simulation.submitted_at is not None:
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

    # Recalculate answered count and total questions
    answers = list(simulation.answers.all())
    total_questions = len(answers)
    answered_count = sum(1 for a in answers if a.answer.strip())

    # Update status immediately based on status rules
    if answered_count == 0:
        simulation.status = Status.GENERATED
        simulation.save(update_fields=["status", "updated_at"])
    elif answered_count < total_questions:
        simulation.status = Status.IN_PROGRESS
        simulation.save(update_fields=["status", "updated_at"])
    else:
        # transition to COMPLETED and kick off background evaluation
        if simulation.status != Status.COMPLETED:
            simulation.status = Status.COMPLETED
            simulation.analysis_status = AnalysisStatus.PENDING
            simulation.submitted_at = timezone.now()
            simulation.save(update_fields=["status", "analysis_status", "submitted_at", "updated_at"])
            run_evaluation_in_background(simulation.id)
        else:
            simulation.save(update_fields=["status", "updated_at"])

    logger.info(
        f"Saved answer: simulation_id={simulation.id}, "
        f"answered_count={answered_count}, status={simulation.status}"
    )

    return JsonResponse({"success": True})


@login_required
@require_POST
def submit_simulation_view(request, simulation_id):
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return HttpResponseForbidden("You do not own this simulation.")

    # Duplicate submission — already submitted, just redirect
    if simulation.submitted_at is not None:
        return redirect(f"/interviews/simulation/{simulation_id}/results/")

    answers = list(simulation.answers.all())
    answered_count = sum(1 for a in answers if a.answer.strip())

    simulation.status = Status.COMPLETED
    simulation.analysis_status = AnalysisStatus.PENDING
    simulation.submitted_at = timezone.now()
    simulation.save(update_fields=["status", "analysis_status", "submitted_at", "updated_at"])

    logger.info(
        f"Saved answer: simulation_id={simulation.id}, "
        f"answered_count={answered_count}, status={simulation.status}"
    )

    logger.info(
        f"simulation_submitted: Simulation {simulation_id} submitted by "
        f"{request.user.username} — {answered_count}/{len(answers)} answered"
    )

    # Fire async evaluation — non-blocking
    run_evaluation_in_background(simulation_id)

    return redirect(f"/interviews/simulation/{simulation_id}/results/")


@login_required
def simulation_results_view(request, simulation_id):
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return HttpResponseForbidden("You do not own this simulation.")

    if simulation.status == Status.IN_PROGRESS:
        return HttpResponseForbidden("In-progress simulations cannot view results.")

    answers = list(simulation.answers.all().order_by("order"))
    total_questions = len(answers)
    answered_count = sum(1 for a in answers if a.answer.strip())
    unanswered_count = total_questions - answered_count

    # Extract ai_analysis blob sections
    ai = simulation.ai_analysis or {}
    strengths = ai.get("strengths", [])
    if isinstance(strengths, str):
        strengths = [strengths]
    weaknesses = ai.get("weaknesses", [])
    if isinstance(weaknesses, str):
        weaknesses = [weaknesses]
    improvement_plan = ai.get("improvement_plan", [])
    if isinstance(improvement_plan, str):
        improvement_plan = [improvement_plan]
    recommended_topics = ai.get("recommended_topics", [])
    resume_gap = ai.get("resume_gap_analysis", {})

    # Score benchmark labels for template
    score_fields = [
        ("Overall",         simulation.overall_score),
        ("Communication",   simulation.communication_score),
        ("Technical",       simulation.technical_score),
        ("Confidence",      simulation.confidence_score),
        ("Clarity",         simulation.clarity_score),
        ("Problem Solving", simulation.problem_solving_score),
    ]
    score_cards = [
        {"label": label, "score": score, "benchmark": score_label(score)}
        for label, score in score_fields
    ]

    readiness = readiness_label(simulation.readiness_score)

    return render(request, "interviews/simulation_results.html", {
        "simulation": simulation,
        "total_questions": total_questions,
        "answered_count": answered_count,
        "unanswered_count": unanswered_count,
        "answers": answers,
        "score_cards": score_cards,
        "readiness": readiness,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "improvement_plan": improvement_plan,
        "recommended_topics": recommended_topics,
        "resume_gap": resume_gap,
        "analysis_status": simulation.analysis_status,
    })


@login_required
def simulation_analysis_status_view(request, simulation_id):
    """Lightweight JSON endpoint polled by the results page JS."""
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return JsonResponse({"error": "Forbidden"}, status=403)

    return JsonResponse({"status": simulation.analysis_status})


@login_required
def resume_simulation_view(request, simulation_id):
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return HttpResponseForbidden("You do not own this simulation.")

    if simulation.status == Status.COMPLETED:
        return HttpResponseForbidden("Completed simulations cannot resume simulation.")

    return redirect(f"/interviews/simulation/{simulation.id}/?resume=true")


@login_required
def practice_questions_view(request, simulation_id):
    simulation = get_object_or_404(InterviewSimulation, id=simulation_id)

    if simulation.user != request.user:
        return HttpResponseForbidden("You do not own this simulation.")

    if simulation.status != Status.COMPLETED:
        return HttpResponseForbidden("Only completed simulations can be practiced.")

    answers = list(simulation.answers.all().order_by("order"))
    total_questions = len(answers)

    # Load original answers as empty in the practice page to reattempt
    answers_json = {
        "simulationId": simulation.id,
        "autosaveUrl": "",
        "totalQuestions": total_questions,
        "isPractice": True,
        "answers": [
            {
                "id": a.id,
                "order": a.order,
                "questionType": a.question_type,
                "question": a.question,
                "savedAnswer": "",
            }
            for a in answers
        ],
    }

    return render(request, "interviews/simulation_session.html", {
        "simulation": simulation,
        "answers": answers,
        "total_questions": total_questions,
        "completed_count": 0,
        "answers_json": answers_json,
        "is_practice": True,
    })