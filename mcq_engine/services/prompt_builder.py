"""
mcq_engine.services.prompt_builder
=====================================
Public API
----------
    build_analysis_prompt(summary: dict) -> str

Converts the output of ``build_test_summary()`` into a single, structured
prompt string that can be sent to any LLM provider (Groq, OpenAI, Gemini, …).

This module NEVER:
  * calls any AI / network service
  * imports Groq, OpenAI or any third-party AI SDK
  * reads from or writes to the database
  * modifies any Django model

Design goals
------------
* **Deterministic** – identical summary → identical prompt, every time.
* **Provider-agnostic** – the prompt text does not reference a specific model.
* **Self-contained** – all context the LLM needs is embedded in the prompt;
  the caller does not need to pass anything else.
* **Structured** – clearly labelled sections make it easy for the model to
  locate each piece of data and follow the instructions exactly.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Internal section builders
# ---------------------------------------------------------------------------

def _format_summary(summary: dict[str, Any]) -> str:
    """
    Section 2 – Assessment Summary.

    Provides the top-level numeric overview so the LLM has raw performance
    figures before it reads the finer-grained breakdowns.
    """
    lines = [
        "## ASSESSMENT SUMMARY",
        "",
        f"  Experience Level   : {summary.get('experience_level', 'FRESHER')}",
        f"  Topic              : {summary['topic']}",
        f"  Total Questions    : {summary['total_questions']}",
        f"  Correct            : {summary['correct']}",
        f"  Wrong              : {summary['wrong']}",
        f"  I Don't Know (X)   : {summary['unknown']}",
        f"  Score              : {summary['score']} / {summary['total_questions']}",
        f"  Percentage         : {summary['percentage']}%",
        f"  Unknown Percentage : {summary['unknown_percentage']}%",
        f"  Completion Rate    : {summary['completion_rate']}%",
    ]
    return "\n".join(lines)


def _format_difficulty(summary: dict[str, Any]) -> str:
    """
    Section 3 – Difficulty Breakdown.

    Splits performance by difficulty tier so the LLM can identify whether
    the learner struggles with hard questions specifically, or across the board.
    """
    lines = ["## DIFFICULTY BREAKDOWN", ""]

    db = summary["difficulty_breakdown"]
    for level in ("easy", "medium", "hard"):
        bucket = db[level]
        lines += [
            f"  [{level.upper()}]",
            f"    Total    : {bucket['total']}",
            f"    Correct  : {bucket['correct']}",
            f"    Wrong    : {bucket['wrong']}",
            f"    Unknown  : {bucket['unknown']}",
            f"    Accuracy : {bucket['accuracy']}%",
            "",
        ]

    return "\n".join(lines).rstrip()


def _format_subtopics(summary: dict[str, Any]) -> str:
    """
    Section 4 – Subtopic Performance.

    Per-subtopic stats give the LLM the granularity it needs to produce
    actionable, topic-specific revision recommendations rather than vague
    generic advice.
    """
    lines = ["## SUBTOPIC PERFORMANCE", ""]

    sb = summary["subtopic_breakdown"]
    for name, bucket in sb.items():
        lines += [
            f"  [{name}]",
            f"    Total    : {bucket['total']}",
            f"    Correct  : {bucket['correct']}",
            f"    Wrong    : {bucket['wrong']}",
            f"    Unknown  : {bucket['unknown']}",
            f"    Accuracy : {bucket['accuracy']}%",
            "",
        ]

    return "\n".join(lines).rstrip()


def _format_strengths(summary: dict[str, Any]) -> str:
    """
    Section 5 – Detected Strengths (accuracy ≥ 80 %).

    Giving the LLM the pre-computed strength list means it can open with
    positive reinforcement and build the learner's confidence before
    addressing weaker areas.
    """
    lines = ["## DETECTED STRENGTHS", ""]

    strengths = summary["strengths"]
    if strengths:
        for s in strengths:
            lines.append(f"  - {s}")
    else:
        lines.append("  (none detected)")

    return "\n".join(lines)


def _format_weaknesses(summary: dict[str, Any]) -> str:
    """
    Sections 6 & 7 – Weak Areas and Critical Weak Areas.

    Separating standard weak areas (accuracy < 50 %) from critical ones
    (accuracy == 0 % or all-unknown) lets the LLM calibrate the urgency of
    its revision recommendations appropriately.
    """
    lines = []

    # Section 6 – Weak Areas
    lines += ["## DETECTED WEAK AREAS", ""]
    weak = summary["weak_areas"]
    if weak:
        for w in weak:
            lines.append(f"  - {w}")
    else:
        lines.append("  (none detected)")

    lines += ["", "## CRITICAL WEAK AREAS", ""]
    critical = summary["critical_weak_areas"]
    if critical:
        for c in critical:
            lines.append(f"  - {c}")
    else:
        lines.append("  (none detected)")

    return "\n".join(lines)


def _format_instructions() -> str:
    """
    Section 8 – Instructions to the AI.

    Explicit, numbered instructions dramatically reduce hallucination and
    keep the model focused on producing structured, actionable output rather
    than generic praise or filler text.
    """
    return """\
## INSTRUCTIONS TO THE AI

You are an expert interview coach and study advisor.
Using ONLY the data provided above, generate a personalized performance report
for the learner. Follow every rule below without exception.

---

### REPORT SECTIONS (include ALL of these)

1. **Overall Performance Summary**
   Provide exactly 3 to 4 concise bullet points separated by newlines, with NO bullet symbols (do NOT use -, *, •, or numbers). Keep each bullet under 15 words. Outline:
   - Core concept understanding / overall progress.
   - Performance by difficulty (e.g., Easy vs Hard).
   - Key weaknesses/areas needing practice.
   - Next steps / immediate subtopic focus.
   Example:
   Strong understanding of DBMS fundamentals.
   Excellent performance in Easy questions.
   Hard questions require additional practice.
   Focus next on Transactions and Indexing.

2. **Key Strengths**
   Identify subtopics where the learner performed well. Each strength must be a concise string in the format "TopicName: Short explanation (max 10 words)". Do NOT generate paragraphs. Max 3 strengths.
   Example: "Joins: Strong conceptual understanding."

3. **Weak Areas**
   Identify subtopics where the learner struggled. Each weakness must be a concise string in the format "TopicName: Short explanation (max 10 words)". Do NOT generate paragraphs. Max 3 weaknesses.
   Example: "Transactions: Needs conceptual revision."

4. **Knowledge Gaps**
   List subtopics with high skipped ("I Don't Know") counts. Each gap must be a single concise sentence under 15 words. Bullet-style. No paragraphs.
   Example: "ACID properties require revision."

5. **Revision Priority**
   Rank weak and critical subtopics from HIGHEST to LOWEST priority. Each priority must be a concise string in the format "TopicName: One-line reason (max 15 words)". Max 3 items.
   Example: "Transactions: Foundation topic affecting multiple interview questions."

6. **Recommended Study Strategy**
   Provide concrete, actionable checklist items separated by newlines (without bullet characters like -, *, •, or numbers). Maximum 5 checklist items total, under 15 words each. Do NOT write prose/paragraphs.
   Example:
   Review Transactions theory
   Practice Indexing questions
   Revise ACID properties

7. **Estimated Revision Time**
   Provide a brief, single-sentence time estimate (will be ignored by UI, but keep for schema compatibility).

8. **Motivational Feedback**
   Be professional and encouraging. Provide maximum 2 to 3 sentences total. Avoid motivational essays or generic empty praise.

---

### STRICT RULES

- Use concise professional language suitable for an analytics dashboard (resembling GitHub Insights, LeetCode, or LinkedIn Skill Assessment).
- Do NOT use paragraphs or prose where lists/bullets are requested.
- Maximum 2 to 3 sentences for any text field.
- No motivational essays. Keep feedback extremely brief and actionable.
- No repeated information across sections.
- No generic advice. Every recommendation must reference actual weak subtopics.
- Prefer list-friendly formats.
- NEVER include emojis in any output field.

---

### OUTPUT FORMAT

Return ONLY valid JSON. No markdown, no code fences, no extra text.
Use exactly this schema:

{
    "performance_summary": "<string: 3-4 newline-separated bullets, no symbols>",
    "strengths": [
        "<string: TopicName: Explanation>",
        "<string: TopicName: Explanation>"
    ],
    "weaknesses": [
        "<string: TopicName: Explanation>",
        "<string: TopicName: Explanation>"
    ],
    "knowledge_gaps": [
        "<string: gap description 1>",
        "<string: gap description 2>"
    ],
    "revision_priority": [
        "<string: TopicName: Reason>",
        "<string: TopicName: Reason>"
    ],
    "study_strategy": "<string: newline-separated checklist items, no symbols>",
    "estimated_revision_time": "<string: realistic time estimate>",
    "motivation": "<string: 2-3 sentences of genuine, professional encouragement>"
}"""



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_analysis_prompt(summary: dict[str, Any]) -> str:
    """
    Convert a ``build_test_summary()`` dictionary into a structured LLM prompt.

    Parameters
    ----------
    summary : dict
        The pure-Python dictionary returned by
        ``mcq_engine.services.analysis.build_test_summary()``.

    Returns
    -------
    str
        A single, self-contained prompt string ready to be passed as the
        ``user`` message to any LLM provider.

    Notes
    -----
    * The function is deterministic: identical input → identical output.
    * No network calls, no database access, no side effects of any kind.
    """
    sections = [
        # ── Section 1: context ───────────────────────────────────────────
        (
            "## ASSESSMENT CONTEXT\n"
            "\n"
            "This is an interview preparation assessment.\n"
            "The learner has just completed a timed MCQ test and the results\n"
            "have been automatically analysed. Your task is to interpret these\n"
            "results and generate a personalised revision report that helps the\n"
            "learner identify their strengths, address their weaknesses and\n"
            "build the most effective study plan for upcoming interviews."
        ),

        # ── Section 2: summary ───────────────────────────────────────────
        _format_summary(summary),

        # ── Section 3: difficulty breakdown ─────────────────────────────
        _format_difficulty(summary),

        # ── Section 4: subtopic performance ─────────────────────────────
        _format_subtopics(summary),

        # ── Section 5: strengths ─────────────────────────────────────────
        _format_strengths(summary),

        # ── Sections 6 & 7: weak / critical weak areas ───────────────────
        _format_weaknesses(summary),

        # ── Section 8: instructions ──────────────────────────────────────
        _format_instructions(),
    ]

    # Join sections with a blank line separator for clean visual structure
    return "\n\n".join(sections)
