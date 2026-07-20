"""
Seed the TEAP data directories with sample data.
Run this script once to populate the knowledge base and user progress
directories with the sample DTP and competency matrix data.

Usage:
    python -m WAI_agent.data.seed_data
"""

import json
import os
from pathlib import Path


def seed():
    """Seed all data directories with sample data."""
    base_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    # ── Load sample data ──
    with open(base_dir / "sample_dtp.json") as f:
        dtp_data = json.load(f)

    with open(base_dir / "sample_competency_matrix.json") as f:
        competency_data = json.load(f)

    department = competency_data["department"]  # "operations"

    # ── Seed Knowledge Base ──
    kb_dir = base_dir / "knowledge_base" / department
    kb_dir.mkdir(parents=True, exist_ok=True)

    # Write each course as a separate document in the knowledge base
    for course in dtp_data["courses"]:
        doc = {
            "title": course["title"],
            "description": course["description"],
            "topics": course["topics"],
            "content": course["content"],
            "estimated_hours": course["estimated_hours"],
            "key_facts": course.get("key_facts", []),
            "source_dtp": dtp_data["dtp_id"],
            "version": dtp_data["version"],
        }
        filepath = kb_dir / f"{course['course_id']}.json"
        filepath.write_text(json.dumps(doc, indent=2))
        print(f"  ✅ KB document: {filepath.name}")

    # ── Seed User Progress ──
    progress_dir = base_dir / "user_progress" / department
    progress_dir.mkdir(parents=True, exist_ok=True)

    for user in competency_data["users"]:
        user_progress = {
            "user_id": user["user_id"],
            "department": user["department"],
            "display_name": user["display_name"],
            "entry_path": user["entry_path"],
            "current_state": user["current_state"],
            "learning_path_id": user.get("learning_path_id", ""),
            "completed_courses": user.get("completed_courses", []),
            "current_course_id": user.get("current_course_id", ""),
            "quiz_attempts": user.get("quiz_attempts", []),
            "assessment_scores": user.get("assessment_scores", []),
            "best_assessment_score": max(
                [s["score"] for s in user.get("assessment_scores", [])], default=0.0
            ),
            "error_retention_matrix": user.get("error_retention_matrix", {}),
            "bypass_locked": user.get("bypass_locked", False),
            "bypass_attempts": user.get("bypass_attempts", 0),
            "readiness_score": user.get("readiness_score", 0.0),
            "is_at_risk": user.get("readiness_score", 0.0) < 0.60,
            "enrolled_at": "2026-06-25T09:00:00Z",
            "manager_id": user.get("manager_id", "manager"),
            "job_level": user.get("job_level", "individual_contributor"),
        }
        filepath = progress_dir / f"{user['user_id']}.json"
        filepath.write_text(json.dumps(user_progress, indent=2))
        print(f"  ✅ User progress: {filepath.name}")

    print(f"\n🎉 Data seeded successfully for department '{department}'!")
    print(f"   Knowledge base: {len(dtp_data['courses'])} documents")
    print(f"   User progress: {len(competency_data['users'])} users")


if __name__ == "__main__":
    seed()
