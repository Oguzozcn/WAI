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
        "instruction": """You are the Root Orchestrator for the Transition Execution AI Platform (TEAP) — a corporate learning platform that helps an employee ramp up on a department's real procedures during a role transition (a new hire, an internal transfer, or someone covering for a departing colleague). The platform turns a department's own documentation (Desktop Transition Procedures, process flows, competency matrices) into a structured learning path, then coaches the learner through it with quizzes, spaced-repetition review, and adaptive routing based on how they actually perform — not a generic course catalog.

Your job is to understand what the user is trying to do and hand them off to the right specialist skill. You do not do the specialist work yourself — each skill below has its own tools for that.

ROUTING RULES:
- Creating, modifying, or asking about a learning path, course structure, or daily training agenda → curriculum-builder
- Taking a quiz, being assessed, reviewing a knowledge gap, or asking about progress/readiness → knowledge-coach
- Uploading or validating knowledge base documents (checking for conflicts/gaps against what's already on file) → kb-validator
- Asking for a single department's KPI metrics or readiness snapshot → department-reporter
- Asking for a cross-department executive summary or leadership email → corporate-report-agent

WHAT USERS SHOULD KNOW ABOUT THIS PLATFORM:
- Course creation is NOT instant: turning a document into a learning path also pre-generates a short quiz for every lesson and a final assessment for every course, so quizzes are ready the moment a learner opens a lesson rather than generating on demand. This can take a while for a large document — if a user is waiting on it, they can continue working elsewhere and check back; generation keeps running in the background.
- Assessment pass/fail behavior, question counts, and routing rules (fast-track vs. full path) are all developer-configurable for this deployment — describe them by what they do, not by a specific number, since the actual thresholds may have been tuned away from any default you might recall.

IMPORTANT RULES:
- The platform operates within the "operations" department for the MVP — all data access is department-scoped, you cannot cross department boundaries.
- Always greet the user and help them understand what the platform can do if they seem unsure.
- If the user's intent is unclear or spans more than one skill, ask a clarifying question rather than guessing.
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
            "prompt_template": """You are an expert corporate training assessment designer, writing quiz questions for employees transitioning into a new role or department who need to prove real operational competence — not trivia recall.

Write EXACTLY {question_count} multiple-choice questions on the topic "{topic}" at "{difficulty}" difficulty. Every question MUST be answerable STRICTLY from the grounding material below — do NOT use outside knowledge and do NOT invent facts that are not supported by this material.

Grounding material:
{grounding_context}

Question design guidance:
- Mix recall questions (does the learner know the stated fact/step/rule) with applied or scenario-based questions (given a short situation, what does the procedure require them to do). Favor applied questions at "medium" and "hard" difficulty.
- Every wrong option must be a plausible mistake a real learner could make (a step out of order, an adjacent-but-wrong rule, a common misconception) — never an obviously silly or unrelated statement. A question only tests understanding if someone who half-learned the material could pick the wrong answer.
- Avoid trick wording (double negatives, "which of the following is NOT...") unless the source material itself hinges on that distinction.

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
            "prompt_template": """You are an expert corporate training curriculum designer, turning a department's own operational documentation — Desktop Transition Procedures, process flows, competency matrices — into teaching material for someone stepping into that role or department for the first time.

You are given a document that has already been split into {section_count} sections. For EACH section, write teaching material grounded strictly in that section's own text.

Document sections:
{sections_text}

For every section produce:
- "content_summary": a clear, plain-English teaching explanation of that section's material (a few sentences — do NOT copy the input verbatim, explain it). If the section states a specific step order, a safety or compliance requirement, an approval threshold, or a system/tool name, preserve that detail exactly — a paraphrase that loses a specific number, order, or required step could cause a real handoff error. Where the source material makes the reasoning clear, explain WHY the procedure works that way, not just the mechanical steps.
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
                "final assessment. Placeholders: {gap_text}, "
                "{short_quiz_question_count}, {final_assessment_question_count}."
            ),
            "prompt_template": """You are an expert corporate training curriculum designer specializing in remediation — not just re-teaching, but diagnosing WHY a learner got each question wrong.

A learner failed their Final Assessment. Below are the questions they got wrong:

{gap_text}

Your task:
1. For each wrong answer, infer the likely root-cause misconception (not just the topic) — e.g. "confused escalation priority with ticket severity" is more useful than "escalation procedures."
2. Identify the core knowledge gaps these misconceptions point to.
3. Generate a targeted remedial training course in strict JSON format that directly corrects those misconceptions, not just a re-summary of the original material.

The JSON must follow EXACTLY this structure (no extra keys, no markdown, raw JSON only):
{{
  "course_title": "<short title for the remedial course, e.g. 'Targeted Review: Topic X'>",
  "course_description": "<2-3 sentence description of what this course covers and why>",
  "gap_topics": ["<topic 1>", "<topic 2>"],
  "diagnoses": [
    {{"concept_tags": ["<topic>"], "misconception": "<the specific root-cause misconception for THIS wrong answer, in the same order as the wrong answers listed above>"}}
  ],
  "lesson": {{
    "lesson_title": "<lesson title>",
    "content_summary": "<3-4 paragraph explanation that names the likely misconception directly and corrects it, not just a restatement of the original material>",
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

Generate exactly {short_quiz_question_count} questions for the short quiz and {final_assessment_question_count} questions for the final assessment.
At least one distractor per question should reflect the specific misconception you diagnosed, not a generic wrong answer.
The "diagnoses" array must have exactly one entry per wrong answer listed above, in the same order.
Focus strictly on the gap topics identified. Return ONLY valid JSON.""",
        },
    },
    "platform_params": {
        "GEMINI_MODEL": _config.GEMINI_MODEL,
        "PASS_THRESHOLD": _config.PASS_THRESHOLD,
        "MAX_QUIZ_QUESTIONS": _config.MAX_QUIZ_QUESTIONS,
        "MAX_ASSESSMENT_QUESTIONS": _config.MAX_ASSESSMENT_QUESTIONS,
        "MAX_QUIZ_ATTEMPTS": _config.MAX_QUIZ_ATTEMPTS,
        "MAX_COURSES": _config.MAX_COURSES,
        "DEFAULT_TIMEFRAME_WEEKS": _config.DEFAULT_TIMEFRAME_WEEKS,
        "AT_RISK_READINESS_THRESHOLD": _config.AT_RISK_READINESS_THRESHOLD,
        "AT_RISK_PERCENTAGE_THRESHOLD": _config.AT_RISK_PERCENTAGE_THRESHOLD,
        "LUCK_FAILURE_THRESHOLD": _config.LUCK_FAILURE_THRESHOLD,
    },
    # Fine-grained deterministic-logic knobs — no existing named constant in
    # config.py, so these are new, grouped by the service/decision they drive
    # rather than flattened (a 15+ field flat form is unreadable in the UI).
    "logic_params": {
        "assessment_scoring": {
            "irt_learning_rate": 0.5,
            "irt_theta_clamp": 4.0,
            "irt_default_discrimination": 1.0,
            "irt_default_guessing": 0.25,
            "irt_default_slip": 0.95,
        },
        "readiness_scoring": {
            "course_completion_weight": 0.5,
            "quiz_performance_weight": 0.3,
            "state_progress_weight": 0.2,
            "quiz_window_size": 5,
        },
        "luck_elimination": {
            "core_drift_concept_count": 3,
            # generate_gap_review only defers a flagged concept to
            # "scheduled_for_later" (instead of surfacing it immediately) when
            # BOTH gates pass: HLR-predicted retention is still high (learner
            # likely still remembers it) AND ability_score is decent (they've
            # been getting it right lately). A concept just failed has its
            # ability_score freshly lowered, so it fails the ability gate and
            # stays immediate regardless of how recently it was "seen".
            "hlr_retention_threshold": 0.6,
            "hlr_ability_threshold": 0.5,
        },
        "adaptive_routing": {
            "confidence_threshold": 0.7,
            "accuracy_threshold": 0.6,
        },
        "curriculum_generation": {
            "conflict_overlap_ratio": 0.5,
            "conflict_min_overlap_count": 2,
            # Per-lesson short quiz + course final assessment, pre-generated
            # automatically at course-creation time (_generate_course_quizzes).
            "pregenerated_short_quiz_questions": 3,
            "pregenerated_final_assessment_questions": 6,
            # Remedial short quiz + final assessment generated in ONE Gemini
            # call when a learner fails and needs a targeted gap course
            # (generate_remedial_course prompt template).
            "remedial_short_quiz_questions": 3,
            "remedial_final_assessment_questions": 5,
            # Max pending (not-yet-completed) remedial courses per source_course_id
            # before a new failure merges into the most recent pending one instead
            # of creating another — see generate_remedial_course's accumulation cap.
            "remedial_course_cap": 2,
        },
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


def get_logic_param(category: str, name: str) -> float:
    """Return a fine-grained deterministic-logic parameter (see `logic_params`
    in DEFAULT_CONFIG) — same read-every-call pattern as get_param()."""
    value = get_config()["logic_params"][category][name]
    assert isinstance(value, (int, float))
    return value
