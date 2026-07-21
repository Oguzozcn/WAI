# Auth & Roles

**Read this page before assuming anything about security.** The MVP uses a deliberately simple, client-trusted model that is appropriate for a local demo and nothing else.

## Login flow

1. `POST /api/auth/login` (`src/api/routes/auth.py`) compares `{user_id, password}` against `data/credentials.json` in plaintext.
2. On success the response `{user_id, display_name, role, manager_id}` is stored by the frontend in **`sessionStorage`** under key `wai-session` (per-tab; closing the tab logs you out).
3. `login.html` redirects to the role's landing page: manager → `/manager-dashboard`, developer → `/dev-console`, everyone else → `/`. An already-logged-in visit to `/login` short-circuits straight to the landing page.

Roles come from `job_level` in credentials: `manager`, `developer`, or `individual_contributor`.

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
| `/`, `/learning-path`, `/lesson`, `/quiz`, `/catalog`, `/chat`, `/learning-paths`, `/settings` | any authenticated user |
| `/knowledge-vault`, `/manager-dashboard`, `/edit-learning-path`, `/learning-materials` | `requireRole('manager')` |
| `/dev-console`, `/documentation` | `requireRole('developer')` |

The sidebar (`sidebar.js: visibleNavLinks()`) mirrors this: manager-only links are filtered out for non-managers; `Agent Console` and `Documentation` are appended only for developers.

## Server-side gating (client-trusted)

Mutating endpoints require a `role` string **supplied by the client** (query param or body field) and check it with a one-line guard:

- `_require_manager(role)` — manager.py, knowledge_base.py
- `_require_developer(role)` — dev_console.py, docs.py

This prevents *accidental* cross-role calls from the UI, not malicious ones — anyone with curl can pass `role=manager`. That is a **known, accepted demo limitation**, consistently applied everywhere rather than half-secured in some places.

## What production would need (GCP migration scope)

- Real identity: Google Identity Platform / IAP, or signed session tokens; server-derived roles.
- Hashed credentials (or no local credentials at all — SSO).
- Server-side authorization middleware on every route, replacing the `role` param pattern.
- Audit logging for manager/developer mutations.

Until then, do not "partially harden" individual endpoints — a mixed model is harder to reason about than the current uniformly-documented one. Track the real fix as part of the cloud migration.
