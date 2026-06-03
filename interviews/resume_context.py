import os
import logging
from resume_analyzer.models import Resume
from resume_analyzer.utils import extract_text_from_pdf, compute_content_hash
from resume_analyzer.ai_analyzer import validate_resume_document,analyze_resume


logger = logging.getLogger(__name__)


def get_resume_context(
    user,
    existing_resume=None,
    uploaded_file=None
):
    """
    Returns structured resume context for interview generation.

    Output:
    {
        "resume": Resume or None,
        "resume_text": str,
        "used_resume_context": bool
    }
    """

    # CASE 1: existing analyzed resume selected
    if existing_resume:
        if existing_resume.user != user:
            raise Exception(
                "Invalid resume selection."
            )

        return {
            "resume": existing_resume,
            "resume_text": existing_resume.extracted_text,
            "used_resume_context": True
        }

    # CASE 2: new uploaded resume
    if uploaded_file:
        temp_path = f"/tmp/{uploaded_file.name}"

        try:
            with open(temp_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)

            extracted_text = extract_text_from_pdf(
                temp_path
            )

            if not extracted_text:
                raise Exception(
                    "We couldn’t process this PDF. Please upload a valid text-based resume."
                )

            if not validate_resume_document(
                extracted_text
            ):
                raise Exception(
                    "Only valid professional resume/CV PDFs are allowed."
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
                    "interview_resume_cache_hit",
                    extra={
                        "user_id": user.id,
                        "content_hash": content_hash
                    }
                )
            else:
                analysis = analyze_resume(extracted_text)
                ats_score = analysis.get("ats_score", 0)
                logger.info(
                    "interview_resume_cache_miss",
                    extra={
                        "user_id": user.id,
                        "content_hash": content_hash
                    }
                )

            resume = Resume.objects.create(
                user=user,
                file=uploaded_file,
                extracted_text=extracted_text,
                ats_score=ats_score,
                analysis_data=analysis,
                content_hash=content_hash
            )

            return {
                "resume": resume,
                "resume_text": extracted_text,
                "used_resume_context": True
            }

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # CASE 3: no resume used
    return {
        "resume": None,
        "resume_text": "",
        "used_resume_context": False
    }