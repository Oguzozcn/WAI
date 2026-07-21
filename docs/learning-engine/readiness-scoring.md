# Readiness Scoring

The readiness score (0.0–1.0) is the single number managers see per employee. It's recomputed by `user_service._recalculate_readiness` after **every** progress update, so it can never go stale.

## The formula

```
readiness = course_completion × 0.5
          + quiz_performance  × 0.3
          + state_progress    × 0.2
```

- **Course completion** — `len(completed_courses) / MAX_COURSES` (10), capped at 1.0.
- **Quiz performance** — mean correctness over the **last 5** quiz attempts (`quiz_window_size`), so old failures stop dragging the score once the learner improves.
- **State progress** — how far along the state machine the learner is (enrolled ≈ 0 → later states higher).
- **Short-circuit**: `current_state == "passed"` → readiness is exactly **1.0** regardless of components.
- Zero activity → 0.0.

All three weights and the window size are tunable live in `logic_params.readiness_scoring` (Agent Console). If you change the weights, keep them summing to 1.0 — nothing enforces it.

## At-risk flagging

`flag_at_risk_users` marks anyone with readiness < **0.6** (`AT_RISK_READINESS_THRESHOLD`) as `is_at_risk`, and sets `blocked_by` to the concept with the highest failure count in their `error_retention_matrix` (defaults to a generic label when no gaps are recorded yet). Department-level alerting triggers when > 25% of a team is below threshold (`AT_RISK_PERCENTAGE_THRESHOLD`).

## Where it surfaces

| Surface | What it shows |
|---------|---------------|
| Manager dashboard reports table | Per-employee readiness, RAG color (`_rag_color`), status label, current course **title** (id resolved via `_resolve_course_title`), biggest blocker |
| Excel export | Same rows, formula-injection-safe |
| `GET /api/department/readiness` | Department aggregate |
| KPI payloads (Tier 2) | Anonymized aggregates only — individual scores never leave Tier A |

## GDPR note

The transition *into* `passed` (which forces readiness to 1.0) is gated by `DataComplianceGate` — it requires a human controller signature + DPIA flag on the event. An `assessment_passed` event without a signature is held for approval; the score keeps being computed from components until a human signs off. This is why a test/user can appear at high-but-not-1.0 readiness despite a passing assessment score.
