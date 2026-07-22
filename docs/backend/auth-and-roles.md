# Auth & Roles

**Read this page before assuming anything about security.** The MVP uses a deliberately simple, client-trusted model that is appropriate for a local demo and nothing else.

## Login flow

1. `POST /api/auth/login` (`src/api/routes/auth.py`) verifies `{user_id, password}` against **bcrypt-hashed** credentials via `src/core/auth_store.py`. Passwords are stored as `password_hash` (a legacy plaintext `password` field is still accepted so an un-migrated file keeps working). The route no longer reads the file or compares plaintext directly.
2. On success the response `{user_id, display_name, role, manager_id}` is stored by the frontend in **`sessionStorage`** under key `wai-session` (per-tab; closing the tab logs you out).
3. `login.html` redirects to the role's landing page: manager → `/manager-dashboard`, developer → `/dev-console`, everyone else → `/`. An already-logged-in visit to `/login` short-circuits straight to the landing page.

Roles come from `job_level` in credentials: `manager`, `developer`, or `individual_contributor`.

### Where credentials live (`src/core/auth_store.py`)

`load_credentials()` resolves accounts from, in order: `WAI_CREDENTIALS_JSON` env (the whole file's content, injected from **Secret Manager** on Cloud Run — so no secret ships in the image or git) → `WAI_CREDENTIALS_PATH` file → `data/credentials.json` (local default). `verify_password` checks bcrypt; `public_entry` returns identity fields with the hash stripped. These are throwaway *demo* accounts — real company access is intended to sit behind Google IAP/SSO (below). Rotate with `scripts/hash_password.py` + a new secret version (see `RUNBOOK.md` §6).

`GET /api/auth/directory/{user_id}` is a small public identity lookup (display_name + role, never the password/hash) used by `profile.html` to resolve a `manager_id` like `"manager"` into a real name ("Reports to Jordan Lee") — 404 if the user_id is unknown.

### IAP-ready identity (`GET /api/auth/iap`)

When the service runs behind Google IAP and `WAI_TRUST_IAP=true`, this endpoint returns the IAP-verified `{authenticated, email}` from the `X-Goog-Authenticated-User-Email` header — letting the frontend seed a session from company SSO instead of the demo login form. With the flag off (the default), the header is ignored (it is spoofable when not actually behind IAP), and the endpoint returns `{authenticated: false}`.

## Client-side gating (`frontend/js/auth.js`)

`window.WisdomAuth` exposes:

- `login(userId, password)` / `logout()`
- `getSession()` → session object or `null`
- `requireAuth()` → redirects to `/login?next=…` when unauthenticated
- `requireRole(role)` → `requireAuth()` + exact role match; mismatch redirects to `/?denied=<role>`, where `sidebar.js` shows an "access denied" toast and strips the query param.

Every page calls one of these in its inline script, immediately after `sidebar.js` loads.

## Page access matrix

| Page | Requirement |
|------|-------------|
| `/`, `/learning-path`, `/lesson`, `/quiz`, `/catalog`, `/chat`, `/learning-paths`, `/settings`, `/profile` | any authenticated user |
| `/support` | any authenticated user (developers are redirected to `/support-console`) |
| `/team-documentation` | `requireAuth()` + in-page redirect: developers are bounced to `/` (they have `/documentation`) |
| `/knowledge-vault`, `/manager-dashboard`, `/edit-learning-path`, `/learning-materials` | `requireRole('manager')` |
| `/dev-console`, `/documentation`, `/support-console`, `/qa-console` | `requireRole('developer')` |

The sidebar (`sidebar.js: visibleNavLinks()`) mirrors this: manager-only links are filtered out for non-managers; `Agent Console` and `Documentation` are appended only for developers. The Support link routes by role (`/support-console` for developers, `/support` otherwise).

## Server-side gating (client-trusted)

Mutating endpoints require a `role` string **supplied by the client** (query param or body field) and check it with a one-line guard:

- `_require_manager(role)` — manager.py, knowledge_base.py, team_docs.py (project creation and deletion only — an employee cannot start or remove a project, only contribute to existing ones)
- `_require_developer(role)` — dev_console.py, docs.py, support.py, uat.py
- `_require_team_member(role)` — team_docs.py: accepts `manager` or `individual_contributor`, rejecting developers (Team Docs is the manager/employee counterpart of the developer docs); used for everything except creating/deleting a project

This prevents *accidental* cross-role calls from the UI, not malicious ones — anyone with curl can pass `role=manager`. That is a **known, accepted demo limitation**, consistently applied everywhere rather than half-secured in some places.

## Production hardening — status

Done (July 2026):
- **Hashed credentials** — bcrypt via `auth_store` (was plaintext).
- **Secrets out of the image/git** — `WAI_CREDENTIALS_JSON` from Secret Manager in cloud.
- **Edge identity ready** — `WAI_TRUST_IAP` + `/api/auth/iap` for Google IAP/SSO in front of Cloud Run (setup steps in `RUNBOOK.md` §5).

Still open (deliberately deferred — **known gap**):
- **Server-side authorization on every route.** Mutating endpoints still trust a client-supplied `role` (see below). IAP secures *who can reach the app* at the edge, which is the important boundary for the MVP; deriving each route's role from the IAP identity server-side is the next focused pass.
- Audit logging for manager/developer mutations.

Do not "partially harden" individual endpoints — a mixed model is harder to reason about than the current uniformly-documented one. Track the route-level fix as one deliberate change.
