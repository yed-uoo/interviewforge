import json
import logging
import threading

from django.db import connection as _db_connection
from .ai_generator import get_groq_client

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark helpers
# ─────────────────────────────────────────────────────────────────────────────

def score_label(score):
    """Return a human-readable benchmark label for a 0-100 score."""
    if score < 40:
        return "Needs Improvement"
    elif score < 60:
        return "Average"
    elif score < 80:
        return "Good"
    else:
        return "Excellent"


def readiness_label(score):
    """Map readiness_score to interview-readiness tier."""
    if score < 40:
        return "Beginner"
    elif score < 70:
        return "Intermediate"
    elif score < 85:
        return "Good"
    else:
        return "Interview Ready"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_evaluation_prompt(simulation, answers, resume_text):
    role = simulation.role
    level = simulation.experience_level

    job_desc = ""
    if simulation.generated_set and simulation.generated_set.job_description:
        job_desc = simulation.generated_set.job_description.strip()

    qa_block = ""
    for i, ans in enumerate(answers, 1):
        q_type = ans.question_type
        question = ans.question.strip()
        answer = ans.answer.strip() if ans.answer else ""

        if not answer:
            answer_display = "[NO ANSWER PROVIDED]"
        elif len(answer) < 20:
            answer_display = f"[VERY SHORT ANSWER]: {answer}"
        else:
            answer_display = answer

        qa_block += (
            f"\n--- Question {i} ({q_type}) ---\n"
            f"Q: {question}\n"
            f"A: {answer_display}\n"
        )

    resume_section = (
        f"Candidate Resume:\n{resume_text[:5000]}"
        if resume_text
        else "Candidate Resume: Not provided."
    )

    n = len(answers)

    prompt = f"""
You are a senior technical interviewer and career coach evaluating a mock interview submission.

Role: {role}
Experience Level: {level}
Job Description: {job_desc if job_desc else "Not provided"}

{resume_section}

Interview Q&A:
{qa_block}

Evaluate the candidate and return ONLY a valid JSON object (no markdown, no commentary).

IMPORTANT SCORING RULES:
1. If an answer is "[NO ANSWER PROVIDED]": assign score 0 to 5.
2. If an answer is "[VERY SHORT ANSWER]" (under 20 characters): heavily penalise confidence and technical scores (score 10 or lower).
3. If an answer is filler/irrelevant (e.g. "I don't know", "N/A", random text): score 15 or lower.
4. If an answer is generic/textbook with no depth: reduce confidence and technical scores by 10-20 points.
5. All scores must be integers between 0 and 100.

RESUME GAP ANALYSIS must cover all three dimensions:
- missing_skills: Skills the role requires but the resume does not show.
- weak_areas: Skills listed on the resume that the candidate failed to demonstrate in answers.
- demonstrated_vs_claimed: Skills on the resume that the candidate articulated well in answers.

Return this exact JSON structure:

{{
    "overall_score": <int 0-100>,
    "communication_score": <int 0-100>,
    "technical_score": <int 0-100>,
    "confidence_score": <int 0-100>,
    "clarity_score": <int 0-100>,
    "problem_solving_score": <int 0-100>,
    "readiness_score": <int 0-100>,
    "strengths": ["...", "...", "..."],
    "weaknesses": ["...", "...", "..."],
    "improvement_plan": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
    "recommended_topics": ["Topic 1", "Topic 2", "Topic 3"],
    "resume_gap_analysis": {{
        "missing_skills": [],
        "weak_areas": [],
        "demonstrated_vs_claimed": []
    }},
    "per_question_analysis": [
        {{
            "question_id": <order int starting at 1>,
            "score": <int 0-100>,
            "feedback": "<2-3 sentence evaluation>",
            "strengths": ["...", "..."],
            "weaknesses": ["...", "..."],
            "improved_answer": "<concise model answer>"
        }}
    ]
}}

The per_question_analysis array MUST have exactly {n} entries in the same order as the questions above.
"""
    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# Schema validator
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_SCORE_KEYS = [
    "overall_score",
    "communication_score",
    "technical_score",
    "confidence_score",
    "clarity_score",
    "problem_solving_score",
    "readiness_score",
]

_REQUIRED_LIST_KEYS = [
    "strengths",
    "weaknesses",
    "improvement_plan",
    "recommended_topics",
]


def _validate_and_clamp(data, expected_question_count):
    for key in _REQUIRED_SCORE_KEYS:
        if key not in data:
            raise ValueError(f"Missing field: {key}")
        val = data[key]
        if not isinstance(val, int):
            try:
                data[key] = int(val)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer, got {val!r}")
        data[key] = max(0, min(100, data[key]))

    for key in _REQUIRED_LIST_KEYS:
        if key not in data:
            raise ValueError(f"Missing field: {key}")
        if not isinstance(data[key], list):
            raise ValueError(f"{key} must be a list")

    if "resume_gap_analysis" not in data or not isinstance(data["resume_gap_analysis"], dict):
        data["resume_gap_analysis"] = {
            "missing_skills": [],
            "weak_areas": [],
            "demonstrated_vs_claimed": [],
        }

    per_q = data.get("per_question_analysis")
    if not isinstance(per_q, list):
        raise ValueError("per_question_analysis must be a list")

    if len(per_q) != expected_question_count:
        raise ValueError(
            f"per_question_analysis has {len(per_q)} entries; expected {expected_question_count}"
        )

    for i, item in enumerate(per_q):
        if not isinstance(item, dict):
            raise ValueError(f"per_question_analysis[{i}] is not a dict")
        item["score"] = max(0, min(100, int(item.get("score", 0))))
        item.setdefault("feedback", "")
        item.setdefault("strengths", [])
        item.setdefault("weaknesses", [])
        item.setdefault("improved_answer", "")

    return data


# ─────────────────────────────────────────────────────────────────────────────
# Core evaluator
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_simulation(simulation_id):
    """
    Called from a background thread. Evaluates the completed simulation,
    writes results to the DB, and updates analysis_status.
    """
    from .models import InterviewSimulation, InterviewSimulationAnswer, AnalysisStatus

    try:
        simulation = (
            InterviewSimulation.objects
            .select_related("generated_set__resume")
            .get(id=simulation_id)
        )
    except InterviewSimulation.DoesNotExist:
        logger.error(f"evaluate_simulation: simulation {simulation_id} not found")
        return

    # Mark PROCESSING
    simulation.analysis_status = AnalysisStatus.PROCESSING
    simulation.save(update_fields=["analysis_status", "updated_at"])

    try:
        answers = list(
            InterviewSimulationAnswer.objects
            .filter(simulation=simulation)
            .order_by("order")
        )

        if not answers:
            raise ValueError("Simulation has no questions to evaluate.")

        # Answer completion score
        total = len(answers)
        answered = sum(1 for a in answers if a.answer.strip())
        completion_score = round(answered / total * 100) if total > 0 else 0

        # Resume text
        resume_text = ""
        try:
            if (
                simulation.generated_set
                and simulation.generated_set.resume
                and simulation.generated_set.resume.extracted_text
            ):
                resume_text = simulation.generated_set.resume.extracted_text
        except Exception:
            pass

        # Build & send prompt
        prompt = _build_evaluation_prompt(simulation, answers, resume_text)
        client = get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=60,
        )

        raw_content = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if raw_content.startswith("```"):
            raw_content = (
                raw_content
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

        start = raw_content.find("{")
        end = raw_content.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("AI response does not contain a valid JSON object.")

        data = json.loads(raw_content[start:end + 1])
        data = _validate_and_clamp(data, len(answers))

        # Save per-question analytics
        per_q = data["per_question_analysis"]
        for i, answer_obj in enumerate(answers):
            q_data = per_q[i]
            answer_obj.score = q_data["score"]
            answer_obj.feedback = q_data.get("feedback", "")
            answer_obj.strengths = q_data.get("strengths", [])
            answer_obj.weaknesses = q_data.get("weaknesses", [])
            answer_obj.improved_answer = q_data.get("improved_answer", "")
            answer_obj.save(update_fields=[
                "score", "feedback", "strengths",
                "weaknesses", "improved_answer", "updated_at",
            ])

        # Build ai_analysis blob
        ai_analysis = {
            "strengths": data["strengths"],
            "weaknesses": data["weaknesses"],
            "improvement_plan": data["improvement_plan"],
            "recommended_topics": data["recommended_topics"],
            "resume_gap_analysis": data["resume_gap_analysis"],
            "per_question_analysis": per_q,
        }

        # Save simulation-level fields
        simulation.overall_score = data["overall_score"]
        simulation.communication_score = data["communication_score"]
        simulation.technical_score = data["technical_score"]
        simulation.confidence_score = data["confidence_score"]
        simulation.clarity_score = data["clarity_score"]
        simulation.problem_solving_score = data["problem_solving_score"]
        simulation.readiness_score = data["readiness_score"]
        simulation.answer_completion_score = completion_score
        simulation.score = data["overall_score"]   # backward compat
        simulation.ai_analysis = ai_analysis
        simulation.analysis_status = AnalysisStatus.COMPLETED

        simulation.save(update_fields=[
            "overall_score", "communication_score", "technical_score",
            "confidence_score", "clarity_score", "problem_solving_score",
            "readiness_score", "answer_completion_score",
            "score", "ai_analysis", "analysis_status", "updated_at",
        ])

        logger.info(
            f"evaluation_completed: simulation {simulation_id} "
            f"scored {data['overall_score']}/100"
        )

    except Exception as exc:
        logger.error(
            f"evaluation_failed: simulation {simulation_id} — {exc}",
            exc_info=True,
        )
        try:
            simulation.analysis_status = AnalysisStatus.FAILED
            simulation.save(update_fields=["analysis_status", "updated_at"])
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Background runner (MVP — no Celery required)
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate_in_thread(simulation_id):
    """
    Thread target: runs the evaluator then releases the PostgreSQL connection
    held by this thread. NOT called directly by tests — use evaluate_simulation.
    """
    try:
        evaluate_simulation(simulation_id)
    finally:
        # Close the thread-local DB connection so the connection pool and
        # the Django test runner can reclaim it cleanly.
        _db_connection.close()


def run_evaluation_in_background(simulation_id):
    """
    Spawn a daemon thread to evaluate the simulation without blocking the
    HTTP request. Safe for Django dev server and gunicorn.
    """
    t = threading.Thread(
        target=_evaluate_in_thread,
        args=(simulation_id,),
        daemon=True,
        name=f"eval-sim-{simulation_id}",
    )
    t.start()
    logger.info(
        f"evaluation_thread_started: simulation {simulation_id} thread={t.name}"
    )
