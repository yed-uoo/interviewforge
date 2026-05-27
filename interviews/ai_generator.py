import json
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


def generate_interview_questions(
    role,
    experience_level,
    job_description="",
    resume_text="",
    used_resume_context=False
):
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
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.4
        )

        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = (
                content
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

        data = json.loads(content)

        required_keys = [
            "hr_questions",
            "technical_questions",
            "coding_questions"
        ]

        for key in required_keys:
            if key not in data:
                raise Exception(
                    "Malformed AI response."
                )

        return data

    except Exception as e:
        print("INTERVIEW AI ERROR:", e)

        raise Exception(
            "Interview generation temporarily unavailable. Please try again shortly."
        )