# Documentation Maintenance

How this documentation system itself works, and the rules for keeping it alive. **Documentation that doesn't match the code is worse than no documentation** — treat doc updates as part of the change, not an afterthought.

## How it's built

- **Content**: plain markdown files in `docs/<section>/<page>.md`, tracked in git — readable on GitHub, diffable in PRs, and trivially editable by humans *and* AI agents.
- **Structure**: `docs/manifest.json` is the single source of truth for the tree — sections (`id`, `title`, `icon`) containing pages (`id`, `title`, `file`). The UI nav, the API, and the exporters all read it.
- **API**: `src/api/routes/docs.py` — `GET /api/docs/tree`, `GET/PUT /api/docs/page/{section}/{page}` (PUT is developer-gated), `GET /api/docs/export?format=txt|pdf&scope=all|<section>/<page>`.
- **UI**: `/documentation` (developer role) — tree nav, rendered view (`markdown.js`), in-place editor with Save, and Download buttons (TXT/PDF, current page or everything).
- **Page ids are validated against the manifest** — they never touch the filesystem directly, so the API can't be used for path traversal.

## Editing docs

Three equally valid ways; all end up in the same files:

1. **The UI** — open `/documentation`, pick a page, Edit → Save. Best for quick fixes during a review.
2. **Any editor** — edit `docs/**/*.md` directly and refresh.
3. **An AI agent** — point it at `docs/` + `manifest.json`. The intended future workflow: after a code change lands, the agent diffs what changed and updates the affected pages automatically. Until that's wired up, ask the agent explicitly ("update the docs for the change we just made") — the file layout was designed so this requires no special tooling.

## Adding a page

1. Create `docs/<section>/<new-page>.md` starting with a single `# Title`.
2. Add `{ "id": "<new-page>", "title": "…", "file": "<section>/<new-page>.md" }` to that section's `pages` in `manifest.json` (order in the array = order in the nav).
3. Refresh — no server restart needed (everything is read per-request).

Adding a section is the same, plus `id`/`title`/`icon` (a Material Symbols name).

## Writing rules

- Start every page with `# Title` matching the manifest title.
- Cross-link with `[text](/documentation?page=<section>/<page>)` — query-param links keep sidebar highlighting working.
- Supported markdown: h1–h4, bold/italic, `inline code`, fenced code blocks, links, ordered/unordered lists, blockquotes, tables, horizontal rules (see `frontend/js/markdown.js`).
- Name real files/functions (`quiz_service.evaluate_answers`) so readers can grep; avoid line numbers — they rot fastest.
- Record *why* decisions were made, not just what the code does — the code already says what.
- Dates: absolute ("July 2026"), never relative ("recently").

## When code changes, which docs change?

| You changed… | Update… |
|--------------|---------|
| A route (new/renamed/reshaped) | backend/api-reference |
| A service function or its behavior | backend/services (+ the relevant learning-engine page) |
| Anything in `src/core/` | backend/core-modules (+ learning-engine/remediation if policy-related) |
| Thresholds/params/prompts | agent-system/dev-console |
| A page, sidebar, or shared JS | frontend/* pages |
| Auth/roles/gating | backend/auth-and-roles |
| Dependencies or storage layout | architecture/tech-stack, architecture/data-and-persistence |
| Tests/UAT process | operations/testing |

## Downloads

TXT = the raw markdown (whole-set export concatenates all pages with section headers). PDF = server-rendered via fpdf2. Both stream with `Content-Disposition: attachment` — hand the PDF to architects who don't have the app running.
