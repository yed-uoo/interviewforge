import json
import os
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

ROLE_SKILLS = {
    "Frontend Developer": [
        "HTML",
        "CSS",
        "JavaScript",
        "TypeScript",
        "React",
        "DOM",
        "Browser APIs",
        "Performance",
        "Responsive Design",
        "Accessibility"
    ],

    "Backend Developer": [
        "Python",
        "Django",
        "REST APIs",
        "Databases",
        "Authentication",
        "Caching",
        "ORM",
        "Deployment",
        "System Design"
    ],

    "Full Stack Developer": [
        "React",
        "State management",
        "Component architecture",
        "API integration",
        "Performance optimization",
        "Responsive design",
        "Authentication UI",
        "Routing",
        "APIs",
        "Database design",
        "Authentication",
        "Caching",
        "Background jobs",
        "Scalability",
        "Docker",
        "Deployment",
        "CI/CD",
        "Monitoring",
        "Architecture decisions"
    ],

    "Data Analyst": [
        "SQL",
        "Python",
        "Pandas",
        "NumPy",
        "Statistics",
        "Visualization"
    ],

    "DevOps Engineer": [
        "Linux",
        "Docker",
        "CI/CD",
        "Kubernetes",
        "AWS",
        "Networking"
    ]
}

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
        "junior",
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

    matched_role_key = None
    role_lower = role.lower()
    if "frontend" in role_lower:
        matched_role_key = "Frontend Developer"
    elif "backend" in role_lower:
        matched_role_key = "Backend Developer"
    elif "full stack" in role_lower or "fullstack" in role_lower:
        matched_role_key = "Full Stack Developer"
    elif "data analyst" in role_lower or "analyst" in role_lower:
        matched_role_key = "Data Analyst"
    elif "devops" in role_lower:
        matched_role_key = "DevOps Engineer"

    role_skills_str = ""
    special_instructions = ""
    if matched_role_key:
        skills = ROLE_SKILLS[matched_role_key]
        role_skills_str = f"Relevant Skills/Technologies for {matched_role_key}:\n" + "\n".join(f"- {s}" for s in skills)

        if matched_role_key == "Frontend Developer":
            special_instructions = (
                "ROLE-SPECIFIC RULES for Frontend Developer:\n"
                "1. Technical questions must be distributed as: 70% frontend questions, 20% general software engineering, 10% backend knowledge.\n"
                "2. AVOID: Django, Database schema, Authentication implementation, Backend APIs, Python internals, and resume projects unrelated to frontend."
            )
        elif matched_role_key == "Backend Developer":
            special_instructions = (
                "ROLE-SPECIFIC RULES for Backend Developer:\n"
                "1. Technical questions must be distributed as: 70% backend, 20% system design, 10% frontend awareness.\n"
                "2. Focus technical questions on: Python, Django, REST APIs, Authentication, Databases, Caching, ORM, System Design, Performance, Deployment."
            )
        elif matched_role_key == "Full Stack Developer":
            special_instructions = (
                "ROLE-SPECIFIC RULES for Full Stack Developer:\n"
                "1. Technical questions must be distributed as: 40% frontend, 40% backend, 20% architecture/system design.\n"
                "2. Frontend topics should include: React, State management, Component architecture, API integration, Performance optimization, Responsive design, Authentication UI, Routing.\n"
                "3. Backend topics should include: APIs, Database design, Authentication, Caching, Background jobs, Scalability.\n"
                "4. System topics should include: Docker, Deployment, CI/CD, Monitoring, Architecture decisions."
            )
        elif matched_role_key == "Data Analyst":
            special_instructions = (
                "ROLE-SPECIFIC RULES for Data Analyst:\n"
                "1. Generate technical questions from: SQL, Python, Pandas, NumPy, Statistics, Visualization, ETL, Data Cleaning."
            )
        elif matched_role_key == "DevOps Engineer":
            special_instructions = (
                "ROLE-SPECIFIC RULES for DevOps Engineer:\n"
                "1. Generate technical questions from: Linux, Docker, CI/CD, Kubernetes, AWS, Networking, or Monitoring."
            )

    if used_resume_context:
        prompt = f"""
You are an expert technical interviewer. You have carefully read the candidate's resume and will conduct a highly personalized interview.

The selected role is:
{role}

The candidate experience level is:
{experience_level}

{role_skills_str}
{special_instructions}

Treat the candidate's resume as the primary source of interview questions. Reference their projects, technologies, and decisions explicitly by name.

Optional job description:
{job_description if job_description else "Not provided"}

Candidate resume:
{resume_text[:6000]}

Generate:

1. 5 HR questions
2. 7 technical questions
3. 3 coding questions

IMPORTANT RULES FOR QUESTIONS:

1. All questions must align with the selected role.

2. STRONG PROJECT GROUNDING & NO HALLUCINATIONS:
   - Extract projects, technologies, skills, responsibilities, and internships/work experience from the resume. Questions must be built from these.
   - Reference candidate project names and technologies explicitly.
   - Never invent projects, companies, technologies, internships, or skills. Only use information explicitly present in the resume.

3. PRIORITY ORDER FOR QUESTION GENERATION:
   1. Resume Projects
   2. Resume Technologies
   3. Target Role
   4. Job Description
   5. General Interview Knowledge

4. COMBINE TARGET ROLE + CANDIDATE RESUME:
   - Build scenario-based questions connecting the candidate's projects to the selected role.
   - If a project on the resume is backend-focused but the selected role is Frontend Developer, ask how they would implement the frontend for that project (e.g., 'You built InterviewForge using Django. If you were asked to build the frontend using React, how would you structure the application?').

5. STRICT PERCENTAGE AND PROJECT COVERAGE QUOTAS:
   - At least 6 of the 15 total generated questions (at least 40%) must directly reference the candidate's resume.
   - At least one question must be generated for every major project listed in the resume.
   - Prefer project-based scenario questions (e.g., 'How did you...' and 'How would you...') over generic theory questions.

6. GUARANTEE PROJECT QUESTIONS PER SECTION:
   - HR Questions: At least 2 of the 5 HR questions must reference the candidate's resume projects.
   - Technical Questions: At least 3 of the 7 technical questions must reference projects or technologies from the resume.
   - Coding Questions: At least 2 of the 3 coding questions must be based directly on projects, technologies, skills, or responsibilities from the resume.

7. CODING QUESTIONS DESIGN RULES:
   - Coding questions must simulate real project work based on the candidate's resume (e.g., 'Build a React resume upload component', 'Create an API endpoint for interview analysis', 'Implement role-based access control', 'Implement JWT authentication', 'Implement file upload service').
   - NEVER generate generic coding questions like 'Remove vowels', 'Count characters', 'Reverse strings', or 'Basic array questions' when resume context is present.

8. Coding questions must match experience level:
    - fresher → arrays, strings, hashmaps, SQL basics, API logic
    - junior → practical CRUD, APIs, authentication basics, debugging, ORM usage, deployment basics
    - mid → API design, debugging, optimization, DB design
    - senior → architecture, scalability, distributed systems

9. HR questions must be realistic recruiter questions.

10. Return ONLY valid JSON.
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

The selected role is:
{role}

The candidate experience level is:
{experience_level}

{role_skills_str}
{special_instructions}

Generate interview questions.

Optional job description:
{job_description if job_description else "Not provided"}

Generate:

1. 5 HR questions
2. 7 technical questions
3. 3 coding questions

IMPORTANT RULES:

1. The selected role has the highest priority.

2. Generate technical questions primarily from the technologies, concepts, and responsibilities associated with this role.

3. At least 80% of questions must directly evaluate skills expected for the selected role.

4. Questions should progressively increase in difficulty.

5. Avoid repeating concepts.

6. Avoid generic questions.

7. Questions should sound like real interview questions asked by companies.

8. Coding questions must match experience level:
    - fresher → arrays, strings, hashmaps, SQL basics, API logic
    - junior → practical CRUD, APIs, authentication basics, debugging, ORM usage, deployment basics
    - mid → API design, debugging, optimization, DB design
    - senior → architecture, scalability, distributed systems

9. HR questions must be realistic recruiter questions.

10. Return ONLY valid JSON.
- No markdown
- No explanations

OUTPUT JSON ONLY:

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