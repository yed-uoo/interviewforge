# InterviewForge

InterviewForge is an AI-powered interview preparation platform that helps candidates analyze resumes, identify improvement areas, and generate personalized interview questions based on their skills, experience, and target roles.

## Features

### Resume Analyzer
- Upload PDF resumes for AI-powered analysis
- Extract resume content using PyMuPDF
- Generate ATS compatibility scores
- Identify strengths, weaknesses, and missing skills
- Recommend suitable job roles
- Maintain resume analysis history

### AI Interview Generator
- Generate HR, Technical, and Coding interview questions
- Role-based interview preparation
- Optional Job Description alignment
- Resume-aware personalized question generation
- Interview generation history tracking

### Reliability & Validation
- PDF validation and text extraction checks
- Input sanitization and validation
- Structured prompt engineering
- JSON response validation
- Timeout and API failure handling
- Malformed response detection

## Tech Stack

Backend
- Python
- Django

AI
- Groq API
- Llama 3.3 70B Versatile

Resume Processing
- PyMuPDF

Frontend
- HTML
- Bootstrap 5

Database
- PostgreSQL

## System Architecture

User → Django Views → Validation → Resume Parsing → Prompt Engineering → Groq API → Response Validation → Database Persistence → Result Rendering

## Resume Analysis Workflow

1. User uploads a PDF resume.
2. Resume text is extracted using PyMuPDF.
3. Resume content is validated.
4. Structured prompts are sent to Groq.
5. AI generates ATS insights and recommendations.
6. Responses are validated and stored.
7. Results are displayed to the user.

## Interview Generation Workflow

1. User selects role and experience level.
2. Optional Job Description and Resume context are provided.
3. Resume text is extracted from uploaded or previously analyzed resumes.
4. Structured prompts are generated dynamically.
5. Groq generates personalized interview questions.
6. Responses are validated and stored.
7. Questions are categorized and displayed.

## Key Highlights

- AI-powered ATS resume evaluation
- Resume-aware interview question generation
- Structured prompt engineering for consistent outputs
- Persistent analysis and interview history
- Robust validation and failure handling
- Modular Django architecture

## Installation

### Clone Repository

git clone https://github.com/yourusername/interviewforge.git cd interviewforge 

### Create Virtual Environment

python -m venv venv 

### Activate Environment

Windows:

venv\Scripts\activate 

Linux/macOS:

source venv/bin/activate 

### Install Dependencies

pip install -r requirements.txt 

### Configure Environment Variables

Create a .env file:

env GROQ_API_KEY=your_groq_api_key 

### Apply Migrations

python manage.py makemigrations python manage.py migrate 

### Run Server

python manage.py runserver 

Visit:

http://127.0.0.1:8000 

## Future Enhancements

- AI Mock Interview Simulator
- AI Answer Evaluation
- Coding Challenges Module
- Skill Gap Roadmaps
- Resume Tailoring for Job Descriptions
- Performance Analytics Dashboard

## Author

Yedu Krishnan

Built to help candidates prepare more effectively for technical interviews through AI-driven resume analysis and interview preparation.
