# Testing & UAT

## Test suite layout

```
tests/
├── conftest.py            # TestClient fixture + temp WAI_DATA_DIR (never touches real data/)
├── unit/                  # Pure logic, no server
│   ├── test_state_machine.py        # Transition graph, Case 1/2 verdicts
│   ├── test_remediation_policy.py   # decide_remediation fusion logic
│   ├── test_luck_elimination.py     # Flagging thresholds, HLR math
│   ├── test_luck_elimination_hook.py# Agent hook blocking behavior
│   ├── test_gap_review_hlr.py       # Due-filtering (retention boundary = 0.5 at Δt = half-life)
│   ├── test_user_service.py         # 22 tests: events, readiness formula, at-risk, GDPR gate
│   ├── test_ingestion.py            # Splitter, sectioning
│   └── test_llm_generation.py       # Prompt building, fallback paths
├── integration/           # FastAPI TestClient against real routes
│   ├── test_auth_routes.py, test_progress_routes.py
│   ├── test_learning_path_routes.py, test_quiz_routes.py   # incl. remediation E2E:
│   │                        # diagnosis persistence, remedial cap, HLR filtering
│   ├── test_kb_routes.py, test_manager_routes.py, test_chat_route.py
│   └── test_docs_routes.py          # documentation system (tree/get/save/export)
└── eval/                  # LLM evals — require live ADC; skipped in normal runs
```

```bash
python3 -m pytest tests/ -q          # the regression gate — keep it green
python3 -m pytest tests/unit -q      # fast inner loop
```

Suite status as of 2026-07-21: **103+ passed, 2 deselected** (eval tests needing ADC). LLM-dependent code paths are tested through their deterministic fallbacks and by mocking `call_gemini_json`.

## Conventions

- Integration tests get isolation via `WAI_DATA_DIR` pointing at a pytest temp dir (conftest) — you can freely create users/paths/quizzes.
- When touching remediation, run the four remediation unit files *plus* `test_quiz_routes.py`; they were written specifically to make that subsystem safe to refactor.
- New route ⇒ new integration test file (or extend the matching one). New core logic ⇒ unit tests alongside the change, not after.

## UAT approach

Full-product UAT is done live against a running server with a real browser — unit/integration green is necessary but not sufficient (three of the last UAT "bugs" turned out to be test-harness artifacts; browser verification settles it).

- **Interactive UAT console** — a shareable checklist artifact covering auth (all 7 accounts), role gating, every page per role, the enroll→lesson→quiz→fail→remediation flow, the pass path, manager reporting/export, dev console, and chat. Sections marked "AUTO PASS" were verified by automation; the rest are for a human pass.
- **Automation harness** — headless Chrome driven over the CDP protocol (Python `websockets`); scripts live outside the repo (scratch), the pattern: launch Chrome with `--headless=new --remote-debugging-port`, open a target, `Page.navigate` + `Runtime.evaluate`, collect console/network errors per page, screenshot.

### UAT gotchas discovered the hard way (do not rediscover these)

1. **Clear `sessionStorage` between scripted logins** — `/login` short-circuits for an existing session, so consecutive logins silently reuse the first session.
2. **`?denied=` disappears fast** — sidebar.js strips it via `history.replaceState` right after showing the toast; assert on the toast text, not the URL.
3. **`innerText` excludes `display:none` content** — dashboard cards beyond 5 are hidden behind "View all courses"; click the toggle before asserting card content exists.
