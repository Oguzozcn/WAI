"""
Seed the TEAP data directories with Vertex AI sample data.
"""

import json
import os
from pathlib import Path
import shutil


def seed():
    """Seed all data directories with Vertex AI sample data."""
    base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    department = "operations"

    # ── Load sample data ──
    with open(base_dir / "vertex_ai_dtp.json") as f:
        dtp_data = json.load(f)

    # We will reuse the competency matrix users, just reset their progress
    with open(base_dir / "sample_competency_matrix.json") as f:
        competency_data = json.load(f)

    # ── Clear existing Knowledge Base ──
    kb_dir = base_dir / "knowledge_base" / department
    if kb_dir.exists():
        shutil.rmtree(kb_dir)
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

    # ── Reset and Seed User Progress ──
    progress_dir = base_dir / "user_progress" / department
    if progress_dir.exists():
        shutil.rmtree(progress_dir)
    progress_dir.mkdir(parents=True, exist_ok=True)

    for user in competency_data["users"]:
        # Reset all progress to simulate a fresh start
        user_progress = {
            "user_id": user["user_id"],
            "department": user["department"],
            "display_name": user["display_name"],
            "entry_path": user["entry_path"],
            "current_state": "enrolled",  # Reset to enrolled
            "learning_path_id": "",
            "completed_courses": [],
            "current_course_id": "",
            "quiz_attempts": [],
            "assessment_scores": [],
            "best_assessment_score": 0.0,
            "error_retention_matrix": {},
            "bypass_locked": False,
            "bypass_attempts": 0,
            "readiness_score": 0.0,
            "is_at_risk": True, # At risk until they do something
            "enrolled_at": "2026-06-25T09:00:00Z",
            "manager_id": user.get("manager_id", "manager"),
            "job_level": user.get("job_level", "individual_contributor"),
        }
        filepath = progress_dir / f"{user['user_id']}.json"
        filepath.write_text(json.dumps(user_progress, indent=2))
        print(f"  ✅ User progress reset: {filepath.name}")

    print(f"\n🎉 Vertex AI data seeded successfully for department '{department}'!")
    print(f"   Knowledge base: {len(dtp_data['courses'])} documents")
    print(f"   User progress: {len(competency_data['users'])} users reset")


if __name__ == "__main__":
    seed()
