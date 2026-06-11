import json
import os

# pyrefly: ignore [missing-import]
from django.core.management.base import BaseCommand, CommandError

from mcq_engine.models import Topic, Subtopic, Question


REQUIRED_FIELDS = [
    "topic",
    "subtopic",
    "difficulty",
    "question",
    "option_a",
    "option_b",
    "option_c",
    "option_d",
    "correct_option",
    "explanation",
]

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_CORRECT_OPTIONS = {"A", "B", "C", "D"}


class Command(BaseCommand):
    help = "Import MCQ questions from a JSON file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="Path to the JSON file containing questions.",
        )

    def handle(self, *args, **options):
        json_file = options["json_file"]

        # ── 1. File existence ────────────────────────────────────────────────
        if not os.path.exists(json_file):
            raise CommandError(f"File not found: '{json_file}'")

        # ── 2. Parse JSON ────────────────────────────────────────────────────
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in '{json_file}': {exc}")

        # ── 3. Root must be a list ───────────────────────────────────────────
        if not isinstance(data, list):
            raise CommandError(
                "JSON root must be a list of question objects, e.g. [{...}, {...}]"
            )

        self.stdout.write(f"\nImporting from: {json_file}")
        self.stdout.write(f"Total records in file: {len(data)}\n")

        # ── Counters ─────────────────────────────────────────────────────────
        processed = 0
        imported = 0
        skipped = 0
        errors = 0

        # ── 4. Process each record ───────────────────────────────────────────
        for index, item in enumerate(data, start=1):
            processed += 1

            # 4a. Must be a dict
            if not isinstance(item, dict):
                self.stderr.write(f"  [#{index}] Skipped — not a JSON object.")
                errors += 1
                continue

            # 4b. Required field presence + non-empty check
            missing = [
                field
                for field in REQUIRED_FIELDS
                if not str(item.get(field, "")).strip()
            ]
            if missing:
                self.stderr.write(
                    f"  [#{index}] Skipped — missing or empty field(s): "
                    f"{', '.join(missing)}"
                )
                errors += 1
                continue

            # 4c. Validate difficulty
            difficulty = str(item["difficulty"]).strip().lower()
            if difficulty not in VALID_DIFFICULTIES:
                self.stderr.write(
                    f"  [#{index}] Skipped — invalid difficulty '{difficulty}'. "
                    f"Allowed: {', '.join(sorted(VALID_DIFFICULTIES))}."
                )
                errors += 1
                continue

            # 4d. Validate correct_option
            correct_option = str(item["correct_option"]).strip().upper()
            if correct_option not in VALID_CORRECT_OPTIONS:
                self.stderr.write(
                    f"  [#{index}] Skipped — invalid correct_option "
                    f"'{correct_option}'. Allowed: A, B, C, D."
                )
                errors += 1
                continue

            question_text = str(item["question"]).strip()

            # 4e. Duplicate check (by question text)
            if Question.objects.filter(question=question_text).exists():
                self.stdout.write(
                    f"  [#{index}] Skipped — duplicate: '{question_text[:60]}'"
                )
                skipped += 1
                continue

            # 4f. get_or_create Topic → Subtopic → create Question
            try:
                topic, _ = Topic.objects.get_or_create(
                    name=str(item["topic"]).strip()
                )
                subtopic, _ = Subtopic.objects.get_or_create(
                    topic=topic,
                    name=str(item["subtopic"]).strip(),
                )
                Question.objects.create(
                    topic=topic,
                    subtopic=subtopic,
                    difficulty=difficulty,
                    question=question_text,
                    option_a=str(item["option_a"]).strip(),
                    option_b=str(item["option_b"]).strip(),
                    option_c=str(item["option_c"]).strip(),
                    option_d=str(item["option_d"]).strip(),
                    correct_option=correct_option,
                    explanation=str(item["explanation"]).strip(),
                )
                imported += 1

            except Exception as exc:
                self.stderr.write(f"  [#{index}] DB error — {exc}")
                errors += 1
                continue

        # ── 5. Summary ───────────────────────────────────────────────────────
        self.stdout.write("\n" + "─" * 42)
        self.stdout.write(f"  Questions Processed : {processed}")
        self.stdout.write(self.style.SUCCESS(f"  Questions Imported  : {imported}"))
        self.stdout.write(self.style.WARNING(f"  Questions Skipped   : {skipped}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"  Errors              : {errors}"))
        else:
            self.stdout.write(f"  Errors              : {errors}")
        self.stdout.write("─" * 42 + "\n")
