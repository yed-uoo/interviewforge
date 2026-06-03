from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import ResumeUploadForm
from .utils import extract_text_from_pdf, compute_content_hash
from .ai_analyzer import analyze_resume, validate_resume_document
from .models import Resume
import os
import logging


logger = logging.getLogger(__name__)


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

                content_hash = compute_content_hash(extracted_text)
                cached_resume = Resume.objects.filter(
                    content_hash=content_hash,
                    ats_score__gt=0
                ).exclude(
                    analysis_data={}
                ).order_by('-uploaded_at').first()

                if cached_resume:
                    analysis = cached_resume.analysis_data
                    ats_score = cached_resume.ats_score
                    logger.info(
                        "resume_cache_hit",
                        extra={
                            "user_id": request.user.id,
                            "content_hash": content_hash
                        }
                    )
                else:
                    analysis = analyze_resume(extracted_text)
                    ats_score = analysis.get('ats_score', 0)
                    logger.info(
                        "resume_cache_miss",
                        extra={
                            "user_id": request.user.id,
                            "content_hash": content_hash
                        }
                    )

                resume = form.save(commit=False)
                resume.user = request.user
                resume.extracted_text = extracted_text
                resume.ats_score = ats_score
                resume.analysis_data = analysis
                resume.content_hash = content_hash
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