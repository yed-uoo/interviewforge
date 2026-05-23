from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .forms import ResumeUploadForm
from .utils import extract_text_from_pdf


@login_required
def upload_resume(request):
    if request.method == 'POST':
        form = ResumeUploadForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():
            resume = form.save(commit=False)
            resume.user = request.user
            resume.save()

            extracted_text = extract_text_from_pdf(
                resume.file.path
            )

            resume.extracted_text = extracted_text
            resume.save()

            return render(
                request,
                'resume_analyzer/result.html',
                {'resume': resume}
            )

    else:
        form = ResumeUploadForm()

    return render(
        request,
        'resume_analyzer/upload.html',
        {'form': form}
    )