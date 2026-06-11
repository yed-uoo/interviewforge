from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.utils import timezone
from django.contrib import messages

from .forms import AssessmentConfigForm
from .models import MCQTest, MCQTestQuestion, MCQAnswer, Topic, Question
from .services.test_generator import generate_test, InsufficientQuestionsError


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
            
            try:
                # Generate questions for the test session
                questions = generate_test(topic.id, question_count)
                
                # Create the MCQTest session
                mcq_test = MCQTest.objects.create(
                    user=request.user,
                    topic=topic,
                    total_questions=question_count,
                    status=MCQTest.Status.IN_PROGRESS
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


@login_required
def test_results_view(request, test_id):
    mcq_test = get_object_or_404(MCQTest, pk=test_id)
    
    # Access control
    if mcq_test.user != request.user:
        return HttpResponseForbidden("You are not authorized to view these results.")
        
    # Redirect active tests to test session page
    if mcq_test.status != MCQTest.Status.COMPLETED:
        return redirect('mcq_test_session', test_id=mcq_test.id)
        
    # Fetch questions and answers
    test_questions = (
        MCQTestQuestion.objects
        .filter(test=mcq_test)
        .select_related('question')
        .order_by('order')
    )
    
    # Build dictionary of answers for quick access
    answers = MCQAnswer.objects.filter(test=mcq_test)
    answers_dict = {ans.question_id: ans for ans in answers}
    
    # Attach answers to question objects for convenient template rendering
    questions_data = []
    for tq in test_questions:
        q = tq.question
        ans = answers_dict.get(q.id)
        questions_data.append({
            'question': q,
            'order': tq.order,
            'answer': ans,
            # helper fields to support UI highlighting
            'is_correct': ans.is_correct if ans else False,
            'selected_option': ans.selected_option if ans else 'X',
        })
        
    return render(request, 'mcq_engine/result.html', {
        'test': mcq_test,
        'questions_data': questions_data
    })
