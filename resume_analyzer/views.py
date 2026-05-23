from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .forms import ResumeUploadForm
from .utils import extract_text_from_pdf
from .ai_analyzer import analyze_resume


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

            analysis = analyze_resume(extracted_text)

            return render(
                request,
                'resume_analyzer/result.html',
                {
                    'analysis': analysis
                }
            )

    else:
        form = ResumeUploadForm()

    return render(
        request,
        'resume_analyzer/upload.html',
        {'form': form}
    )