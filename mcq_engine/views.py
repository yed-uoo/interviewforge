import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.contrib import messages

from .forms import AssessmentConfigForm
from .models import MCQTest, MCQTestQuestion, MCQAnswer, Topic, Question
from .services.test_generator import generate_test, InsufficientQuestionsError
from .services.analysis_cache import get_or_generate_analysis

logger = logging.getLogger(__name__)


@login_required
def setup_test_view(request):
    if request.method == 'POST':
        print("=" * 50)
        print("MCQ SETUP POST RECEIVED")
        print("POST DATA:", request.POST)
        print("=" * 50)

        print("VALIDATING FORM")
        form = AssessmentConfigForm(request.POST)
        print("FORM VALID:", form.is_valid())
        if not form.is_valid():
            print("FORM ERRORS:", form.errors)

        if form.is_valid():
            topic = form.cleaned_data['topic']
            question_count = form.cleaned_data['question_count']
            experience_level = form.cleaned_data['experience_level']
            
            try:
                # Generate questions for the test session
                questions = generate_test(topic.id, question_count, experience_level)
                
                # Create the MCQTest session
                mcq_test = MCQTest.objects.create(
                    user=request.user,
                    topic=topic,
                    total_questions=question_count,
                    status=MCQTest.Status.IN_PROGRESS,
                    experience_level=experience_level,
                )
                print("MCQ TEST CREATED:", mcq_test.id)
                
                # Add questions with orders
                test_questions = [
                    MCQTestQuestion(test=mcq_test, question=question, order=i+1)
                    for i, question in enumerate(questions)
                ]
                MCQTestQuestion.objects.bulk_create(test_questions)
                print("TEST QUESTIONS CREATED")
                
                print("REDIRECTING TO TEST:", mcq_test.id)
                return redirect('mcq_test_session', test_id=mcq_test.id)
                
            except InsufficientQuestionsError as exc:
                form.add_error('question_count', str(exc))
    else:
        form = AssessmentConfigForm()
        
    return render(request, 'mcq_engine/setup.html', {
        'form': form,
    })


@login_required
def test_history_view(request):
    past_tests = (
        MCQTest.objects
        .filter(user=request.user)
        .select_related('topic')
        .order_by('-created_at')
    )
    total_count      = past_tests.count()
    completed_count  = past_tests.filter(status=MCQTest.Status.COMPLETED).count()
    in_progress_count = total_count - completed_count

    return render(request, 'mcq_engine/history.html', {
        'past_tests':        past_tests,
        'total_count':       total_count,
        'completed_count':   completed_count,
        'in_progress_count': in_progress_count,
    })


@login_required
def test_session_view(request, test_id):
    mcq_test = get_object_or_404(MCQTest, pk=test_id)
    
    # Access control
    if mcq_test.user != request.user:
        return HttpResponseForbidden("You are not authorized to access this test session.")
        
    # Redirect completed tests to results
    if mcq_test.status == MCQTest.Status.COMPLETED:
        return redirect('mcq_results', test_id=mcq_test.id)
        
    test_questions = (
        MCQTestQuestion.objects
        .filter(test=mcq_test)
        .select_related('question')
        .order_by('order')
    )
    
    if request.method == 'POST':
        correct_count = 0
        answers_to_create = []
        
        # Grade each question and prepare answers
        for tq in test_questions:
            q_id = tq.question.id
            selected_option = request.POST.get(f'question_{q_id}', '').upper()
            
            # If not chosen, default to 'X' (I Don't Know)
            if selected_option not in ['A', 'B', 'C', 'D', 'X']:
                selected_option = 'X'
                
            is_correct = (selected_option == tq.question.correct_option)
            if is_correct:
                correct_count += 1
                
            answers_to_create.append(
                MCQAnswer(
                    test=mcq_test,
                    question=tq.question,
                    selected_option=selected_option,
                    is_correct=is_correct
                )
            )
            
        # Bulk create answers
        MCQAnswer.objects.bulk_create(answers_to_create)
        
        # Update test results
        mcq_test.score = correct_count
        mcq_test.percentage = (correct_count / mcq_test.total_questions) * 100
        mcq_test.status = MCQTest.Status.COMPLETED
        mcq_test.submitted_at = timezone.now()
        mcq_test.save()
        
        return redirect('mcq_results', test_id=mcq_test.id)
        
    return render(request, 'mcq_engine/session.html', {
        'test': mcq_test,
        'test_questions': test_questions
    })


def _parse_insight(text, subtopic_buckets):
    """
    Parse a single insight string (strength/weakness/priority) from AI.
    Handles colon/dash separators: "TopicName: Description" or "TopicName — Description".
    Finds matching subtopic name from subtopic_buckets to resolve accuracy/severity.
    """
    text = text.strip()
    topic = None
    desc = text

    # Try matching by split first
    for sep in (':', '—', '-'):
        if sep in text:
            parts = text.split(sep, 1)
            candidate = parts[0].strip()
            # If candidate matches a subtopic name (case-insensitive), use it
            for st_name in subtopic_buckets:
                if st_name.lower() == candidate.lower():
                    topic = st_name
                    desc = parts[1].strip()
                    break
            if topic:
                break

    # If no match by split, check if any subtopic name exists as a substring
    if not topic:
        for st_name in subtopic_buckets:
            if st_name.lower() in text.lower():
                topic = st_name
                desc = text
                break

    # Fallback if no subtopic detected
    if not topic:
        topic = text
        desc = ""

    # Get accuracy
    accuracy = None
    if topic in subtopic_buckets:
        accuracy = subtopic_buckets[topic]['accuracy']

    return {
        'topic': topic,
        'accuracy': accuracy,
        'description': desc
    }


@login_required
def test_results_view(request, test_id):
    mcq_test = get_object_or_404(MCQTest, pk=test_id)

    # Access control
    if mcq_test.user != request.user:
        return HttpResponseForbidden("You are not authorized to view these results.")

    # Redirect active tests to test session page
    if mcq_test.status != MCQTest.Status.COMPLETED:
        return redirect('mcq_test_session', test_id=mcq_test.id)

    # Fetch questions and answers in two efficient queries
    test_questions = (
        MCQTestQuestion.objects
        .filter(test=mcq_test)
        .select_related('question', 'question__subtopic')
        .order_by('order')
    )
    answers = MCQAnswer.objects.filter(test=mcq_test)
    answers_dict = {ans.question_id: ans for ans in answers}

    # ── Build questions_data + compute analytics in a single pass ──────────
    questions_data = []

    diff_buckets   = {
        'easy':   {'correct': 0, 'wrong': 0, 'unknown': 0, 'total': 0},
        'medium': {'correct': 0, 'wrong': 0, 'unknown': 0, 'total': 0},
        'hard':   {'correct': 0, 'wrong': 0, 'unknown': 0, 'total': 0},
    }
    subtopic_buckets = {}  # name → {correct, wrong, unknown, total}

    estimated_minutes = 0  # heuristic revision estimate

    for tq in test_questions:
        q   = tq.question
        ans = answers_dict.get(q.id)

        is_correct      = ans.is_correct if ans else False
        selected_option = ans.selected_option if ans else 'X'
        is_unknown      = (selected_option == 'X')

        questions_data.append({
            'question':        q,
            'order':           tq.order,
            'answer':          ans,
            'is_correct':      is_correct,
            'selected_option': selected_option,
        })

        # ── Difficulty bucket ──────────────────────────────────────────
        diff_key = q.difficulty.lower()
        b = diff_buckets.get(diff_key, diff_buckets['medium'])
        b['total'] += 1
        if is_unknown:
            b['unknown'] += 1
        elif is_correct:
            b['correct'] += 1
        else:
            b['wrong'] += 1

        # ── Subtopic bucket ────────────────────────────────────────────
        st_name = q.subtopic.name
        if st_name not in subtopic_buckets:
            subtopic_buckets[st_name] = {'correct': 0, 'wrong': 0, 'unknown': 0, 'total': 0}
        sb = subtopic_buckets[st_name]
        sb['total'] += 1
        if is_unknown:
            sb['unknown'] += 1
        elif is_correct:
            sb['correct'] += 1
        else:
            sb['wrong'] += 1

        # ── Estimated revision time (only for incorrect/unknown) ────────
        if not is_correct:
            if diff_key == 'hard':
                estimated_minutes += 15
            elif diff_key == 'medium':
                estimated_minutes += 10
            else:
                estimated_minutes += 5

    # Add per-subtopic base cost for weak subtopics (accuracy < 50%)
    for sb_data in subtopic_buckets.values():
        if sb_data['total'] > 0:
            acc = sb_data['correct'] / sb_data['total']
            if acc < 0.5:
                estimated_minutes += 30

    # Add accuracy to each bucket
    for b in diff_buckets.values():
        b['accuracy'] = round((b['correct'] / b['total'] * 100), 1) if b['total'] else 0.0
    for sb_data in subtopic_buckets.values():
        sb_data['accuracy'] = round(
            (sb_data['correct'] / sb_data['total'] * 100), 1
        ) if sb_data['total'] > 0 else 0.0

    # Format revision time
    if estimated_minutes == 0:
        estimated_revision = "< 30 min"
    elif estimated_minutes < 60:
        estimated_revision = f"≈ {estimated_minutes} min"
    elif estimated_minutes < 120:
        h = estimated_minutes // 60
        m = estimated_minutes % 60
        estimated_revision = f"≈ {h}h {m}m" if m else f"≈ {h}h"
    else:
        hours = round(estimated_minutes / 60, 1)
        estimated_revision = f"≈ {hours} hrs"

    # ── AI Analysis (cache-aside) ────────────────────────────────────────
    analysis = None
    try:
        analysis = get_or_generate_analysis(mcq_test)
    except Exception as exc:
        logger.exception(
            "mcq_ai_analysis_failed test_id=%s error=%s", mcq_test.pk, exc
        )

    processed_strengths = []
    processed_weaknesses = []
    processed_priorities = []
    strategy_items = []

    if analysis:
        # Strengths
        for s in analysis.get('strengths', []):
            if isinstance(s, str):
                processed_strengths.append(_parse_insight(s, subtopic_buckets))

        # Weaknesses
        for w in analysis.get('weaknesses', []):
            if isinstance(w, str):
                parsed = _parse_insight(w, subtopic_buckets)
                severity = "Needs Revision"
                acc = parsed['accuracy']
                if acc is not None:
                    if acc < 35.0:
                        severity = "Critical"
                    elif acc < 60.0:
                        severity = "Needs Revision"
                    else:
                        severity = "Needs Practice"
                parsed['severity'] = severity
                processed_weaknesses.append(parsed)

        # Priorities
        for idx, item in enumerate(analysis.get('revision_priority', [])):
            if isinstance(item, str):
                parsed = _parse_insight(item, subtopic_buckets)
                parsed['num'] = idx + 1
                processed_priorities.append(parsed)

        # Strategy checklist
        raw_strategy = analysis.get('study_strategy', '')
        if isinstance(raw_strategy, str):
            for line in raw_strategy.splitlines():
                line = line.strip().lstrip('-').lstrip('*').lstrip('□').lstrip('•').strip()
                if line:
                    strategy_items.append(line)

    return render(request, 'mcq_engine/result.html', {
        'test':                 mcq_test,
        'questions_data':       questions_data,
        'analysis':             analysis,
        'difficulty_breakdown': diff_buckets,
        'subtopic_breakdown':   subtopic_buckets,
        'estimated_revision':   estimated_revision,
        'processed_strengths':  processed_strengths,
        'processed_weaknesses': processed_weaknesses,
        'processed_priorities': processed_priorities,
        'strategy_items':       strategy_items,
    })


