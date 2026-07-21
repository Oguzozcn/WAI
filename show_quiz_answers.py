#!/usr/bin/env python3
"""Dev-only helper: print a quiz's correct answers so you can deliberately
pass or fail it while manually testing through the browser.

The API always strips correct_answer_index from responses (see
tests/integration/test_quiz_routes.py::test_generate_quiz_returns_sanitized_questions) -
this script reads the same data straight off disk, where it's never sanitized.

Usage:
    python3 show_quiz_answers.py --quiz-id quiz_039e4c68
    python3 show_quiz_answers.py --user-id emp_001
    python3 show_quiz_answers.py --user-id emp_001 --department operations -v
"""
import argparse
import sys

from src.core.database import DepartmentScopedStore

LETTERS = "ABCD"


def _print_question(i: int, q: dict, verbose: bool) -> None:
    correct = q.get("correct_answer_index")
    tags = q.get("concept_tags", [])
    print(f"\n  Q{i}. {q.get('text', '(no text)')}")
    if tags:
        print(f"      concept_tags: {', '.join(tags)}")
    for j, opt in enumerate(q.get("options", [])):
        marker = "✔" if j == correct else " "
        print(f"      [{marker}] {LETTERS[j] if j < 4 else j}. {opt}")
        if verbose:
            rationale = q.get("rationale", {}).get(str(j))
            if rationale:
                print(f"            -> {rationale}")


def _print_quiz(quiz: dict, verbose: bool, label: str = "") -> None:
    if not quiz:
        print(f"  (not found){' - ' + label if label else ''}")
        return
    header = f"{quiz.get('quiz_id', label)} [{quiz.get('quiz_type', '?')}] - {quiz.get('topic', '')}"
    print(f"\n{'=' * len(header)}\n{header}\n{'=' * len(header)}")
    for i, q in enumerate(quiz.get("questions", []), 1):
        _print_question(i, q, verbose)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiz-id", help="Look up a single quiz from the quiz store by id.")
    parser.add_argument("--user-id", help="Show a user's in-progress quiz attempts and any pending remedial-course quizzes.")
    parser.add_argument("--department", default="operations", help="Department scope (default: operations).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Also print per-option rationale.")
    args = parser.parse_args()

    if not args.quiz_id and not args.user_id:
        parser.error("pass --quiz-id and/or --user-id")

    store = DepartmentScopedStore(args.department)

    if args.quiz_id:
        _print_quiz(store.read_quiz(args.quiz_id), args.verbose, label=args.quiz_id)

    if args.user_id:
        progress = store.read_user_progress(args.user_id)
        if not progress:
            print(f"No progress record for user_id={args.user_id!r} in department={args.department!r}")
            return 1

        attempts = progress.get("quiz_attempts", [])
        print(f"\n--- {args.user_id}: {len(attempts)} quiz attempt(s) on record ---")
        for a in attempts:
            print(f"  {a.get('quiz_id', '?')}: {a.get('correct_answers', '?')}/{a.get('total_questions', '?')} "
                  f"correct (score={a.get('score')}) at {a.get('attempted_at', '?')}")

        remedial_courses = progress.get("remedial_courses", [])
        if not remedial_courses:
            print("\n(no pending remedial courses)")
        for rc in remedial_courses:
            print(f"\n--- Remedial course: {rc.get('course_id')} ({rc.get('title')}) "
                  f"targeting {rc.get('source_course_id', '?')} ---")
            for lesson in rc.get("lessons", []):
                sq = lesson.get("short_quiz")
                if sq:
                    _print_quiz(sq, args.verbose, label=f"{rc.get('course_id')} short_quiz")
            fa = rc.get("final_assessment")
            if fa:
                _print_quiz(fa, args.verbose, label=f"{rc.get('course_id')} final_assessment")

    return 0


if __name__ == "__main__":
    sys.exit(main())
