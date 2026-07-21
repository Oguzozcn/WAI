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
| `/settings` | settings.html | any user | Account info, theme toggle, logout |
| `/knowledge-vault` | knowledge-vault.html | manager | Document upload, ingestion jobs, conflict review |
| `/learning-materials` | learning-materials.html | manager | KB document management, versions |
| `/edit-learning-path` | edit-learning-path.html | manager | Course/lesson/quiz editing with markdown preview + regenerate |
| `/manager-dashboard` | manager-dashboard.html | manager | Team KPIs, reports table, Excel export, strategic bucket |
| `/dev-console` | dev-console.html | developer | Agent Console (see [Agent Console](/documentation?page=agent-system/dev-console)) |
| `/documentation` | documentation.html | developer | This documentation system |

## Sidebar (`frontend/js/sidebar.js`)

A single IIFE that renders into `<div id="sidebar-mount">` on every page.

- `NAV_LINKS` — the base list (Dashboard, Learning Path, Knowledge Vault, Team Dashboards, Catalog).
- `visibleNavLinks()` — role filtering: non-managers lose the manager-only hrefs; developers get `Agent Console` (`/dev-console`) and `Documentation` (`/documentation`) appended.
- Bottom block: account card (name/role/logout), theme toggle, Settings link. Support link shows a "coming soon" toast.
- `isActive(href)` — **exact** pathname match (trailing slashes stripped; `/` only matches root). Query strings don't break matching — which is why multi-view pages (documentation, lesson, quiz) use query params, never sub-paths.
- Collapse state persists in `localStorage`; the access-denied toast fires when the URL carries `?denied=…` (then strips it via `history.replaceState`).
- Public surface: `window.WisdomSidebar = { toast, isActive, applyTheme, isDarkMode }`.

## Adding a new page — checklist

1. Create `frontend/pages/<name>.html` (copy dev-console.html's head + body skeleton: auth.js, `#sidebar-mount`, `<main class="… sidebar-offset">`, sidebar.js, inline script with the right `requireRole`).
2. Add the route in `src/api/routes/pages.py` (`@router.get("/<name>") → _serve_page("<name>.html")`).
3. If it needs a nav entry, wire it in `sidebar.js` (`NAV_LINKS` or the role-specific append).
4. Update the access matrix in [Auth & Roles](/documentation?page=backend/auth-and-roles) and this page.
