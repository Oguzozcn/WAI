# Pages & Navigation

## How pages work

There is no framework and no build step. Each page is one self-contained HTML file in `frontend/pages/`, served at a top-level URL by `src/api/routes/pages.py: _serve_page`. Pages share behavior via script includes: `auth.js` (top of body) → page markup → `sidebar.js` → the page's own inline `<script>` which starts with a `requireAuth()`/`requireRole()` call.

Every page's `<head>` carries the same boilerplate (copy it from `dev-console.html` when adding a page): anti-flash theme snippet, Google Fonts (Hanken Grotesk / Inter / JetBrains Mono + Material Symbols), Tailwind Play CDN, inline `tailwind.config` with the MD3 color tokens, `/css/dark-mode.css`.

## Page catalog

| URL | File | Access | Purpose |
|-----|------|--------|---------|
| `/login` | login.html | public | Login form; redirects by role; skips ahead if already logged in |
| `/` | dashboard.html | any user | Courses tab (per-lesson cards, incl. remedial "TARGETED REVIEW") + Paths tab; pagination after 5 cards |
| `/learning-path` | learning-path.html | any user | Current path detail with lesson progression |
| `/lesson` | lesson.html | any user | Lesson content (`?course=…&lesson=…`), mini-markdown rendering, start-quiz button |
| `/quiz` | quiz.html | any user | Quiz runner (driven by `quiz-controller.js`) |
| `/catalog` | catalog.html | any user | Published paths; click to enroll |
| `/learning-paths` | learning-paths.html | any user | Enrolled/available paths overview (manager: drafts + publish) |
| `/chat` | chat.html | any user | Coach chat → `POST /api/chat` (ADK agent) |
| `/settings` | settings.html | any user | Compact account summary (links to `/profile`), theme toggle, logout |
| `/profile` | profile.html | any user | Read-only identity (avatar, role, reports-to) + learning snapshot (courses completed, quizzes taken, readiness score, active gaps, status, member since) sourced from `GET /api/user/{id}/progress` |
| `/knowledge-vault` | knowledge-vault.html | manager | Document upload, ingestion jobs, conflict review |
| `/learning-materials` | learning-materials.html | manager | KB document management, versions |
| `/edit-learning-path` | edit-learning-path.html | manager | Course/lesson/quiz editing with markdown preview + regenerate |
| `/manager-dashboard` | manager-dashboard.html | manager | Team KPIs, reports table, Excel export, strategic bucket |
| `/dev-console` | dev-console.html | developer | Agent Console (see [Agent Console](/documentation?page=agent-system/dev-console)) |
| `/documentation` | documentation.html | developer | This documentation system |
| `/support` | support.html | employee/manager | Report-an-issue form (area, issue type, subject, description) + "My tickets" tracker with comments. Developers get redirected to the console |
| `/support-console` | support-console.html | developer | ServiceNow-style queue: status stat cards, filters/search, triage panel (status/priority/assignee/work notes), activity timeline |
| `/qa-console` | qa-console.html | developer | Manual UAT: predefined whole-app checklist grouped by area, per-item Launch pop-up + pass/fail/blocked buttons with notes, AI-generated run report (verdict/risks/recommendations), persistent run history |
| `/team-documentation` | team-documentation.html | employee/manager | Team Docs: per-project documentation workspace — project card grid, docs-style page viewer/editor (`markdown.js`), Add-Page modal (blank / import from Knowledge Vault / AI-drafted), Manage Sources modal (curates a project's `linked_sources`), "Generate Full Documentation" button (Documentation Master — synthesizes the whole doc set from every linked source in one pass), TXT/PDF export. Only a manager can create or delete a project; employees can open, edit, and add pages to any existing one. Developers get redirected to `/` (they have `/documentation`) |

## Sidebar (`frontend/js/sidebar.js`)

A single IIFE that renders into `<div id="sidebar-mount">` on every page.

- `NAV_LINKS` — the base list, ordered to follow the learner's natural flow: Dashboard, Catalog, Learning Path, Knowledge Vault, Team Docs, Team Dashboards (manager-only oversight last, since it's an admin lens rather than part of an individual's own path).
- `visibleNavLinks()` — role filtering: non-managers lose the manager-only hrefs; developers lose the team-only hrefs (`/team-documentation`) and get `Agent Console` (`/dev-console`), `Documentation` (`/documentation`) and `UAT Console` (`/qa-console`) appended.
- Bottom block: account card (name/role/logout), theme toggle, Settings link. The Support link is role-aware: developers go to `/support-console`, everyone else to `/support`.
- `isActive(href)` — **exact** pathname match (trailing slashes stripped; `/` only matches root). Query strings don't break matching — which is why multi-view pages (documentation, lesson, quiz) use query params, never sub-paths.
- Collapse state persists in `localStorage`; the access-denied toast fires when the URL carries `?denied=…` (then strips it via `history.replaceState`).
- Public surface: `window.WisdomSidebar = { toast, isActive, applyTheme, isDarkMode, initials, trackJob }`.
- Header avatar: a page adds `<div id="header-avatar-mount"></div>` to its TopAppBar and `sidebar.js` fills it with a notification bell (background-job completions — see `docs/frontend/shared-modules.md`) plus a session-driven initials circle linking to `/profile` — the single source for what used to be 10 pages' worth of hand-copied, unrelated-to-the-user stock-photo `<img>` tags.
- Chat launcher: a floating bottom-right button linking to `/chat`, mounted on every page with `#sidebar-mount` and a session, except `/chat` itself and `/quiz`.

`/learning-materials`'s file table has a Download button per row (`GET /api/kb/documents/{filename}/download`) alongside version history and delete.

## Adding a new page — checklist

1. Create `frontend/pages/<name>.html` (copy dev-console.html's head + body skeleton: auth.js, `#sidebar-mount`, `<main class="… sidebar-offset">`, sidebar.js, inline script with the right `requireRole`).
2. Add the route in `src/api/routes/pages.py` (`@router.get("/<name>") → _serve_page("<name>.html")`).
3. If it needs a nav entry, wire it in `sidebar.js` (`NAV_LINKS` or the role-specific append).
4. Update the access matrix in [Auth & Roles](/documentation?page=backend/auth-and-roles) and this page.
