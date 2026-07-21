# Shared JS Modules & Theming

All shared behavior lives in `frontend/js/` as plain scripts exposing `window.*` globals. Load order matters: `auth.js` first, `sidebar.js` after the page markup, page-specific scripts last.

## auth.js → `window.WisdomAuth`

Session in `sessionStorage['wai-session']` (per-tab). API: `login`, `logout`, `getSession`, `requireAuth` (redirect to `/login?next=…`), `requireRole` (redirect to `/?denied=<role>` on mismatch). See [Auth & Roles](/documentation?page=backend/auth-and-roles).

## sidebar.js → `window.WisdomSidebar`

Renders the sidebar, handles role-based link visibility, collapse state, theme, and toasts. Public API:

- `toast(message, type)` — bottom-center pill for 3s (`'info'` | `'warn'`). Delegates to a page-level `window.showToast` if the page defines one.
- `isActive(href)` — exact-path matcher used for nav highlighting.
- `applyTheme(dark)` / `isDarkMode()` — the **only** correct way to toggle theme from a page. `applyTheme` flips the `dark` class on `<html>`, persists to `localStorage['wai-theme']`, and updates the sidebar toggle's own label. (Settings once duplicated this logic and drifted out of sync — don't repeat that; call the sidebar's functions.)

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
