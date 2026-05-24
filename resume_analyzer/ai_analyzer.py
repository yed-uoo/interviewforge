import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)


def analyze_resume(resume_text):
    prompt = f"""
You are an expert ATS resume evaluator, technical recruiter, and software engineering hiring manager.

Analyze this resume for software engineering / backend developer internship suitability.

Return ONLY valid JSON.

Required JSON schema:

{{
    "ats_score": integer between 0 and 100,
    "detected_skills": [],
    "missing_skills": [],
    "strengths": [],
    "weaknesses": [],
    "suggestions": [],
    "recommended_roles": []
}}

Evaluation rules:

ATS score:
- ats_score MUST be an integer from 0 to 100
- NEVER use 0–10 scale
- no decimals

ATS scoring rules:
- score conservatively
- penalize missing industry-standard backend engineering skills
- do not inflate scores for student resumes with limited production breadth

General rules:
- raw JSON only
- no markdown
- no explanations
- no extra text

Weakness rules:
- identify ONLY genuine weaknesses supported by the resume
- weaknesses must be specific, technical, and recruiter-relevant
- DO NOT generate vague weaknesses like:
  "Limited Experience"
  "Improve Communication"
  "Need More Projects"
  "Gain More Exposure"
- DO NOT invent unsupported weaknesses
- if the candidate has projects, do NOT call them inexperienced
- focus on concrete missing technical signals such as:
  testing frameworks
  Docker/containerization
  cloud platforms
  CI/CD
  API documentation
  system design exposure
  backend scalability
  caching
  security practices
  monitoring
  deployment tooling

Suggestion rules:
- each suggestion must directly address a listed weakness
- suggestions must be specific and actionable
- avoid generic advice
- each suggestion must be under 10 words
- concise UI-friendly phrasing
- suggestions must be implementation-focused
- avoid passive suggestions like "read", "explore", "learn"

Strength rules:
- strengths must be concrete observations from the resume
- avoid generic praise

Missing skills rules:
- list ONLY the top 5 most relevant missing technical skills
- do NOT generate an exhaustive wishlist
- prioritize realistic backend internship gaps

Recommended roles:
- recommend realistic early-career software roles only
- recommended_roles must use professional title casing

Detected skills rules:
- include both explicit technologies and inferred technical competencies
- examples:
  authentication
  authorization
  backend development
  deployment
  database design
  API development

Resume:
{resume_text}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1
    )

    content = response.choices[0].message.content.strip()

    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()

    return json.loads(content)