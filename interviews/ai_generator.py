import json
import os
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise Exception(
            "AI service configuration missing."
        )

    return Groq(api_key=api_key)

def sanitize_inputs(
    role,
    experience_level,
    job_description,
    resume_text
):
    role = role.strip()
    experience_level = experience_level.strip().lower()
    job_description = job_description.strip()
    resume_text = resume_text.strip()

    if not role:
        raise Exception(
            "Target role is required."
        )

    if len(role) > 100:
        raise Exception(
            "Role input too long."
        )

    if not re.match(
        r"^[a-zA-Z0-9\s\-/()+.&]+$",
        role
    ):
        raise Exception(
            "Invalid role input."
        )

    valid_levels = [
        "fresher",
        "mid",
        "senior"
    ]

    if experience_level not in valid_levels:
        raise Exception(
            "Invalid experience level."
        )

    if len(job_description) > 3000:
        job_description = job_description[:3000]

    if len(resume_text) > 6000:
        resume_text = resume_text[:6000]

    return (
        role,
        experience_level,
        job_description,
        resume_text
    )

def generate_interview_questions(
    role,
    experience_level,
    job_description="",
    resume_text="",
    used_resume_context=False
):
    role, experience_level, job_description, resume_text = sanitize_inputs(

        role,

        experience_level,

        job_description,

        resume_text

    )
    if used_resume_context:
        prompt = f"""
You are an senior technical interviewer.

Generate highly personalized interview questions
based on the candidate's actual resume.

Candidate target role:
{role}

Experience level:
{experience_level}

Optional job description:
{job_description if job_description else "Not provided"}

Candidate resume:
{resume_text[:6000]}

Generate:

1. 5 HR questions
2. 7 technical questions
3. 3 coding questions

STRICT RULES:

1. NEVER invent projects, companies, systems, products, or experience not explicitly present in resume context.

2. If resume context exists:

   - ground technical questions ONLY in stated skills, tools, technologies, and projects

   - ask follow-up questions based on actual evidence

   - do NOT hallucinate fictional systems

3. If no resume context:

   - generate role-realistic but generic questions

   - do NOT assume specific projects

4. Coding questions must match experience level:

   - fresher → arrays, strings, hashmaps, SQL basics, API logic

   - mid → API design, debugging, optimization, DB design

   - senior → architecture, scalability, distributed systems

5. HR questions must be realistic recruiter questions.

6. Technical questions must sound like a real engineering interviewer.

Rules:
- Ask about technologies ACTUALLY present in the resume
- Ask project-specific questions
- Ask architecture/design questions if projects suggest backend depth
- Never create logically inconsistent coding questions.
- Match difficulty to experience level
- If job description exists, partially align questions to JD
- Maintain stack consistency
- Do NOT hallucinate unrelated tech stacks
- Return ONLY valid JSON
- No markdown
- No explanations

OUTPUT JSON ONLY:

{{
    "hr_questions": [],
    "technical_questions": [],
    "coding_questions": []
}}
"""

    else:
        prompt = f"""
You are an expert technical interviewer.

Generate interview questions for:

Target role:
{role}

Experience level:
{experience_level}

Optional job description:
{job_description if job_description else "Not provided"}

Generate:

1. 5 HR questions
2. 7 technical questions
3. 3 coding questions

Rules:
- Match difficulty to experience level
- If JD exists, align to JD
- Maintain stack consistency
- Return ONLY valid JSON
- No markdown
- No explanations

JSON format:

{{
    "hr_questions": [],
    "technical_questions": [],
    "coding_questions": []
}}
"""

    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.4,
            timeout=20
        )

        if not response:
            raise Exception(
                "No AI response received."
            )

        if not response.choices:
            raise Exception(
                "Empty AI response."
            )

        message = response.choices[0].message

        if not message:
            raise Exception(
                "Missing AI response message."
            )

        if not message.content:
            raise Exception(
                "Blank AI response."
            )

        content = message.content.strip()

        if content.startswith("```"):
            content = (
                content
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

        start = content.find("{")
        end = content.rfind("}")

        if start == -1 or end == -1:
            raise Exception(
                "Malformed AI response."
            )

        json_content = content[start:end + 1]

        data = json.loads(json_content)

        expected_schema = {
            "hr_questions": 5,
            "technical_questions": 7,
            "coding_questions": 3
        }

        for key, expected_count in expected_schema.items():
            if key not in data:
                raise Exception(
                    f"Missing AI response field: {key}"
                )

            if not isinstance(data[key], list):
                raise Exception(
                    f"{key} must be a list."
                )

            if len(data[key]) != expected_count:
                raise Exception(
                    f"{key} has invalid question count."
                )

            for item in data[key]:
                if not isinstance(item, str):
                    raise Exception(
                        f"{key} contains invalid data."
                    )

        return data

    except Exception as e:
        print("INTERVIEW AI ERROR:", e)

        error_message = str(e).lower()

        if "timeout" in error_message:
            raise Exception(
                "Interview generation took too long. Please try again."
            )

        raise Exception(
            "Interview generation temporarily unavailable. Please try again shortly."
        )