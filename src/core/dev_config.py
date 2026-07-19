"""Developer-editable platform configuration.

Backs the Agent Console (developer-only page): the orchestrator's routing
instruction, the 3 Gemini prompt templates the platform actually calls
(process_document_to_curriculum / generate_remedial_course / generate_quiz),
and a handful of tunable platform parameters — all readable/writable without
a code deploy.

Skill personas are intentionally NOT duplicated here — `.agents/skills/*/SKILL.md`
stays the single source of truth (ADK already loads it from disk at agent-
construction time); the console reads/writes those files directly instead.

Follows the same lightweight, read-every-call JSON-file pattern the rest of
the app already uses (see auth.py's data/credentials.json, or database.py's
DepartmentScopedStore) — no caching layer, self-heals on read.
"""

import copy
import json
from pathlib import Path
from typing import Any

from src.core import config as _config

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEV_CONFIG_PATH = PROJECT_ROOT / "data" / "dev_config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "orchestrator": {
        "model": "gemini-3.5-flash",
        "instruction": """You are the Root Orchestrator for the Transition Execution AI Platform (TEAP).

Your job is to understand the user's intent and invoke the correct declarative skill or tool.

ROUTING RULES:
- If the user wants to create/modify a training plan or learning path → use the curriculum-builder skill
- If the user wants to take a quiz or be assessed → use the knowledge-coach skill
- If the user wants to upload or validate knowledge base documents → use the kb-validator skill
- If the user wants department KPI metrics → use the department-reporter skill
- If the user wants corporate-level reports → use the corporate-report-agent skill

IMPORTANT RULES:
- The platform operates within the "operations" department for the MVP
- Always greet the user and help them understand what the platform can do
- If the user's intent is unclear, ask a clarifying question
- All data access is department-scoped — you cannot cross department boundaries
""",
    },
    "tools": {
        "generate_quiz": {
            "model": "gemini-3.5-flash",
            "description": (
                "Grounded multiple-choice quiz generator — used by both the "
                "on-demand quiz endpoints and course-creation pre-generation. "
                "Placeholders: {question_count}, {topic}, {difficulty}, {grounding_context}."
            ),
            "prompt_template": """You are an expert corporate training assessment designer.

Write EXACTLY {question_count} multiple-choice questions on the topic "{topic}" at "{difficulty}" difficulty. Every question MUST be answerable STRICTLY from the grounding material below — do NOT use outside knowledge and do NOT invent facts that are not supported by this material.

Grounding material:
{grounding_context}

Each question must have exactly 4 options with exactly one correct answer, and a rationale for every option (keyed "0" to "3") explaining why it is correct or incorrect. Provide 1-3 short concept tags per question.

Return ONLY raw JSON (no markdown fences) matching EXACTLY this shape:
{{
  "questions": [
    {{
      "text": "...",
      "options": ["...", "...", "...", "..."],
      "correct_answer_index": 0,
      "rationale": {{"0": "...", "1": "...", "2": "...", "3": "..."}},
      "concept_tags": ["...", "..."]
    }}
  ]
}}

Return exactly {question_count} questions. Do NOT include any "question_id" field.""",
        },
        "process_document_to_curriculum": {
            "model": "gemini-3.5-flash",
            "description": (
                "Course Splitter — turns each structural section of an uploaded "
                "document into a teaching summary + key concepts, in one batched "
                "call. Placeholders: {section_count}, {sections_text}."
            ),
            "prompt_template": """You are an expert corporate training curriculum designer.

You are given a document that has already been split into {section_count} sections. For EACH section, write teaching material grounded strictly in that section's own text.

Document sections:
{sections_text}

For every section produce:
- "content_summary": a clear, plain-English teaching explanation of that section's material (a few sentences — do NOT copy the input verbatim, explain it).
- "key_points": a list of 3-5 short key concept/term strings from that section.

Return ONLY raw JSON (no markdown fences) matching EXACTLY this shape, with one object per input section and matching "index" values:
{{
  "sections": [
    {{"index": 0, "content_summary": "...", "key_points": ["...", "..."]}}
  ]
}}""",
        },
        "generate_remedial_course": {
            "model": "gemini-3.5-flash",
            "description": (
                "Gap-analysis + remedial course generator — given a learner's "
                "wrong quiz answers, produces a targeted lesson + short quiz + "
                "final assessment. Placeholder: {gap_text}."
            ),
            "prompt_template": """You are an expert corporate training curriculum designer.

A learner failed their Final Assessment. Below are the questions they got wrong:

{gap_text}

Your task:
1. Identify the core knowledge gaps from these mistakes.
2. Generate a targeted remedial training course in strict JSON format.

The JSON must follow EXACTLY this structure (no extra keys, no markdown, raw JSON only):
{{
  "course_title": "<short title for the remedial course, e.g. 'Targeted Review: Topic X'>",
  "course_description": "<2-3 sentence description of what this course covers and why>",
  "gap_topics": ["<topic 1>", "<topic 2>"],
  "lesson": {{
    "lesson_title": "<lesson title>",
    "content_summary": "<3-4 paragraph explanation of the gap concepts in plain English>",
    "key_points": ["<key point 1>", "<key point 2>", "<key point 3>"]
  }},
  "short_quiz": {{
    "title": "<short quiz title>",
    "questions": [
      {{
        "text": "<question text>",
        "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
        "correct_answer_index": 0,
        "rationale": {{
          "0": "<why option A is correct or wrong>",
          "1": "<why option B is correct or wrong>",
          "2": "<why option C is correct or wrong>",
          "3": "<why option D is correct or wrong>"
        }},
        "concept_tags": ["<tag>"]
      }}
    ]
  }},
  "final_assessment": {{
    "title": "<final assessment title>",
    "questions": [
      {{
        "text": "<question text>",
        "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
        "correct_answer_index": 0,
        "rationale": {{
          "0": "<rationale>",
          "1": "<rationale>",
          "2": "<rationale>",
          "3": "<rationale>"
        }},
        "concept_tags": ["<tag>"]
      }}
    ]
  }}
}}

Generate exactly 3 questions for the short quiz and 5 questions for the final assessment.
Focus strictly on the gap topics identified. Return ONLY valid JSON.""",
        },
    },
    "platform_params": {
        "GEMINI_MODEL": _config.GEMINI_MODEL,
        "PASS_THRESHOLD": _config.PASS_THRESHOLD,
        "MAX_QUIZ_QUESTIONS": _config.MAX_QUIZ_QUESTIONS,
        "MAX_ASSESSMENT_QUESTIONS": _config.MAX_ASSESSMENT_QUESTIONS,
        "MAX_QUIZ_ATTEMPTS": _config.MAX_QUIZ_ATTEMPTS,
    },
}


def _deep_merge_defaults(data: dict, defaults: dict) -> dict:
    """Fill in any keys missing from `data` using `defaults`, recursively —
    self-heals a config file written by an older DEFAULT_CONFIG schema."""
    for key, default_value in defaults.items():
        if key not in data:
            data[key] = copy.deepcopy(default_value)
        elif isinstance(default_value, dict) and isinstance(data[key], dict):
            _deep_merge_defaults(data[key], default_value)
    return data


def get_config() -> dict:
    """Read data/dev_config.json, self-healing (seeding/filling defaults) if
    the file is missing, corrupt, or predates a newer schema key."""
    if DEV_CONFIG_PATH.exists():
        try:
            data = json.loads(DEV_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    healed = _deep_merge_defaults(data, DEFAULT_CONFIG)
    DEV_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEV_CONFIG_PATH.write_text(json.dumps(healed, indent=2))
    return healed


def update_config(path: list[str], patch: dict) -> dict:
    """Merge `patch` into the config section addressed by `path`
    (e.g. ["orchestrator"] or ["tools", "generate_quiz"]) and persist.

    Returns the full, updated config.
    """
    config = get_config()
    target = config
    for key in path[:-1]:
        target = target.setdefault(key, {})
    leaf_key = path[-1]
    if not isinstance(target.get(leaf_key), dict):
        target[leaf_key] = {}
    target[leaf_key].update(patch)
    DEV_CONFIG_PATH.write_text(json.dumps(config, indent=2))
    return config


def get_param(name: str):
    """Return a platform parameter, preferring a developer-console override
    over the hardcoded default in src/core/config.py."""
    params = get_config()["platform_params"]
    if name in params:
        return params[name]
    return getattr(_config, name)
