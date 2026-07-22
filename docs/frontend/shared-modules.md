# Shared JS Modules & Theming

All shared behavior lives in `frontend/js/` as plain scripts exposing `window.*` globals. Load order matters: `auth.js` first, `sidebar.js` after the page markup, page-specific scripts last.

## auth.js → `window.WisdomAuth`

Session in `sessionStorage['wai-session']` (per-tab). API: `login`, `logout`, `getSession`, `requireAuth` (redirect to `/login?next=…`), `requireRole` (redirect to `/?denied=<role>` on mismatch). See [Auth & Roles](/documentation?page=backend/auth-and-roles).

## sidebar.js → `window.WisdomSidebar`

Renders the sidebar, handles role-based link visibility, collapse state, theme, toasts, background-job notifications, and the chat launcher. Public API:

- `toast(message, type)` — bottom-center pill for 3s (`'info'` | `'warn'`). Delegates to a page-level `window.showToast` if the page defines one.
- `isActive(href)` — exact-path matcher used for nav highlighting.
- `applyTheme(dark)` / `isDarkMode()` — the **only** correct way to toggle theme from a page. `applyTheme` flips the `dark` class on `<html>`, persists to `localStorage['wai-theme']`, and updates the sidebar toggle's own label. (Settings once duplicated this logic and drifted out of sync — don't repeat that; call the sidebar's functions.)
- `trackJob({job_id, kind, department})` — register a background job for the persistent notification poller (see below).

`NAV_LINKS` order (Dashboard → Catalog → Learning Path → Knowledge Vault → Team Docs → Team Dashboards) follows the learner's natural flow — browse/enroll, then your assigned path, then shared reference material — with the manager-only oversight view (Team Dashboards) last since it's an admin lens, not part of an individual's own path.

Since this is a multi-page app, `sidebar.js` re-mounts the sidebar and re-applies the collapsed/expanded state (and the matching `.sidebar-offset`/`.sidebar-offset-header` margin on the page header) from scratch on every navigation. The collapse/expand CSS transition (`margin-left`/`width`, .3s) is gated behind a `body.sidebar-ready` class that's only added a couple of animation frames after the initial state is applied (`injectStyles`/`init` in `sidebar.js`). Without that gate, the very first state application on page load would itself animate — the header/search bar visibly sliding into its offset position on *every* page transition, looking like the sidebar re-opens each time. Only user-triggered collapse/expand clicks (which happen after `sidebar-ready` is set) should ever animate.

`sidebar.js` also owns the header avatar: a page opts in with `<div id="header-avatar-mount"></div>` in its TopAppBar, and `init()` fills it with a notification bell (see below) plus a session-driven initials circle (`headerAvatarHtml()`/`initials()`) linking to `/profile`. This replaced 10 pages' worth of hand-copied `<img src="https://...">` tags — five different hardcoded stock photos with no relationship to who was actually logged in, clickable on only 2 of those 10 pages. `initials` is exposed on `window.WisdomSidebar` so `profile.html`/`settings.html` can render the same avatar math in their own larger/smaller copies instead of re-deriving it (same reuse convention as `applyTheme`/`isDarkMode`).

### Background job notifications (bell in `header-avatar-mount`)

Some server work (Team Docs `ai_draft` pages, `generate-documentation`) runs too long to block a request, so those endpoints return a `job_id` immediately and finish on the server independent of the browser. A page that starts one calls `window.WisdomSidebar.trackJob({job_id, kind, department})`; `sidebar.js` persists pending jobs to `localStorage['wai-pending-jobs']` (not page state) specifically so that *whichever page happens to be open* when the job finishes — not necessarily the one that started it — is the one that notices, and a full navigation never loses track of it. `init()` resumes polling (`JOB_STATUS_URL`, keyed by `kind`) on every page load; on `completed`/`error` it records a `localStorage['wai-notifications']` entry, fires a toast, updates the bell's badge, and dispatches a `wai:job-done` window event carrying the job's result so a still-open page for the same project can refresh in place (`team-documentation.html` listens for this). A job unresolvable for more than `JOB_MAX_AGE_MS` (30 min) is dropped quietly rather than polled forever. Adding a new background-job subsystem means adding one `JOB_STATUS_URL[kind]` entry.

### Wisdom AI chat launcher

A floating bottom-right button (`#wai-chat-launcher`, linking to `/chat`) is mounted on every page that has `#sidebar-mount` and a logged-in session, except `/chat` itself (redundant there) and `/quiz` (an assessment page, where a chat prompt would be a distraction) — see `CHAT_LAUNCHER_EXCLUDED_PATHS`.

## css/entrance.css → `.fade-up` / `.fade-up-2` / `.fade-up-3` / `.fade-up-4`

Shared page-load entrance animation (opacity+translateY, staggered .1s apart, `@media (prefers-reduced-motion: reduce)` disables it). Apply to a page's top-level content blocks (one class per block, in visual order) so every page opens with the same staggered fade Team Dashboard originated — previously `manager-dashboard.html` had its own private copy of this CSS; it now links `/css/entrance.css` like every other page instead. Beyond the visual consistency, staggering the reveal gives an async data fetch a little cover to finish replacing "Loading…"-style placeholder text before the block holding it is even visible, which is the main reason Team Dashboard felt smoother than other pages while they had no masking at all (see `dashboard.html`'s `#dash-course-count`/`#dash-lesson-count` and `quiz.html`'s `passing-score`/`attempts-left`/`description` — those elements had misleading *hardcoded* values baked into the static HTML rather than an honest placeholder, so real data visibly overwrote a wrong-looking value within milliseconds of the page painting; both were changed to honest `—` placeholders). Elements toggled via a `hidden` class (e.g. Team Docs' `#projects-view`/`#project-view`) replay the animation each time they're un-hidden, since CSS animations restart when an element goes from `display: none` to displayed — this is relied on for in-page view switches, not just the initial page load.

## api-client.js

Thin fetch helpers for the JSON API (GET/POST wrappers with error handling). Pages that predate it use raw `fetch` — either is acceptable; prefer the client for new code.

## quiz-controller.js

The quiz runner: loads/starts sessions, renders questions and options, calls `/api/quiz/evaluate/single` per answer (inline right/wrong feedback + reflection panel via `/api/quiz/reflection`), submits the full attempt to `/api/quiz/evaluate`, renders the results screen incl. gap-review exercises with "Start Targeted Retry" buttons. Contains an `escapeHtml` helper (detached-div technique) — reuse it whenever inserting user/LLM text via `innerHTML`.

## global-search.js

Sidebar search box → debounced `GET /api/search?q=…` → dropdown results.

## markdown.js → `window.WisdomMarkdown`

Shared dependency-free markdown renderer (added with the documentation system): `render(md)` → HTML string, `escapeHtml(text)`. Supports h1–h4, bold/italic, inline code, fenced code blocks, links, ordered/unordered lists, blockquotes, tables, horizontal rules. **Escapes all HTML before transforming**, so rendered content can't inject markup. `lesson.html` and `edit-learning-path.html` still carry older regex mini-renderers (`##`/`###`/`**`/```` ```python ````-only); migrating them to `WisdomMarkdown.render` is a welcome cleanup.

## Theming / dark mode

- Theme = the `dark` class on `<html>`, persisted in `localStorage['wai-theme']`.
- Every page's first `<head>` script is the **anti-flash snippet**: reads the stored theme (falling back to `prefers-color-scheme`) and sets the class before first paint.
- Light theme comes from the inline Tailwind config's MD3 tokens; dark theme from `frontend/css/dark-mode.css`, which re-themes the token classes under `.dark` (with `!important` to outrank Tailwind's JIT classes). Brand tokens (primary/secondary) intentionally stay identical across themes.
- Adding a component? Use the semantic token classes (`bg-surface`, `text-on-surface`, `border-outline-variant`…) and dark mode works for free. Hardcode a hex and it won't.

## Conventions

- No bundler; new shared code = a new file in `frontend/js/` + a `<script src>` tag on the pages that need it.
- Escape anything that goes through `innerHTML` unless it's a static template literal.
- Toast, don't `alert()` — `WisdomSidebar.toast` (pages usually define a `showToast` wrapper with an `alert` fallback).
- Material Symbols for all icons (`<span class="material-symbols-outlined">icon_name</span>`).
