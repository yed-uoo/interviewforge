from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import ResumeUploadForm
from .utils import extract_text_from_pdf
from .ai_analyzer import analyze_resume, validate_resume_document
from .models import Resume
import os


@login_required
def upload_resume(request):
    if request.method == 'POST':
        form = ResumeUploadForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():
            uploaded_file = request.FILES['file']
            temp_path = f"/tmp/{uploaded_file.name}"

            with open(temp_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)

            try:
                extracted_text = extract_text_from_pdf(temp_path)

                if not extracted_text:
                    return render(
                        request,
                        'resume_analyzer/upload.html',
                        {
                            'form': ResumeUploadForm(),
                            'error': (
                                'We couldn’t process this PDF. '
                                'Please upload a valid text-based resume PDF.'
                            )
                        }
                    )

                if not validate_resume_document(extracted_text):
                    return render(
                        request,
                        'resume_analyzer/upload.html',
                        {
                            'form': ResumeUploadForm(),
                            'error': (
                                'Only valid professional '
                                'resume/CV PDFs are allowed.'
                            )
                        }
                    )

                analysis = analyze_resume(extracted_text)

                resume = form.save(commit=False)
                resume.user = request.user
                resume.extracted_text = extracted_text
                resume.ats_score = analysis.get('ats_score', 0)
                resume.analysis_data = analysis
                resume.save()

                return render(
                    request,
                    'resume_analyzer/result.html',
                    {
                        'analysis': analysis
                    }
                )

            except Exception as e:
                print("UPLOAD ERROR:", e)

                return render(
                    request,
                    'resume_analyzer/upload.html',
                    {
                        'form': ResumeUploadForm(),
                        'error': (
                            'Resume analysis is temporarily unavailable. '
                            'Please try again shortly.'
                        )
                    }
                )

            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    else:
        form = ResumeUploadForm()

    return render(
        request,
        'resume_analyzer/upload.html',
        {
            'form': form
        }
    )
@login_required
def analysis_history(request):
    resumes = Resume.objects.filter(
        user=request.user
    ).order_by('-uploaded_at')

    return render(
        request,
        'resume_analyzer/history.html',
        {
            'resumes': resumes
        }
    )
@login_required
def view_analysis_report(request, resume_id):
    resume = get_object_or_404(
        Resume,
        id=resume_id,
        user=request.user
    )

    return render(
        request,
        'resume_analyzer/result.html',
        {
            'analysis': resume.analysis_data
        }
    )