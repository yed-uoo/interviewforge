from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .forms import ResumeUploadForm
from .utils import extract_text_from_pdf
from .ai_analyzer import analyze_resume, validate_resume_document
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