/**
 * WisdomAI Global Search
 * ======================
 * Live header search across catalog learning paths and their courses.
 *
 * Wires up the `<input id="global-search-input">` present in the header of
 * dashboard / learning-path / knowledge-vault / learning-materials /
 * learning-paths / catalog pages. Renders a dropdown (a sibling appended inside
 * the input's existing `.relative` wrapper) with grouped "Courses" / "Paths"
 * results fetched from `GET /api/search`.
 *
 * Behaviour mirrors the catalog's enroll-then-navigate UX:
 *   - Path result  -> POST /api/learning-path/{id}/enroll, then /learning-path?path=...
 *   - Course result-> same enroll, then /lesson?course=...&lesson=...
 *
 * Loaded once per page via <script src="/js/global-search.js"></script>.
 */
(function () {
  'use strict';

  // Guard against double-initialisation (mirrors sidebar.js's single-run intent).
  if (window.__wisdomGlobalSearchInit) return;
  window.__wisdomGlobalSearchInit = true;

  function currentUserId() {
    const session = window.WisdomAuth && window.WisdomAuth.getSession();
    return session ? session.user_id : 'emp_001';
  }

  const DEBOUNCE_MS = 300;
  const MIN_CHARS = 2;

  function ready(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn, { once: true });
    } else {
      fn();
    }
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function truncate(str, n) {
    const s = String(str || '').trim();
    if (s.length <= n) return s;
    return s.slice(0, n - 1).trimEnd() + '…';
  }

  ready(function () {
    const input = document.getElementById('global-search-input');
    if (!input) return;

    const wrapper = input.closest('.relative');
    if (!wrapper) return;

    // ── Build the dropdown container ──────────────────────────────────────────
    const dropdown = document.createElement('div');
    dropdown.className =
      'absolute left-0 right-0 top-full mt-2 z-50 bg-surface-container-lowest ' +
      'border border-outline-variant rounded-xl shadow-lg overflow-hidden hidden ' +
      'max-h-96 overflow-y-auto text-sm';
    dropdown.setAttribute('role', 'listbox');
    wrapper.appendChild(dropdown);

    let debounceTimer = null;
    let activeRequestId = 0;

    function hideDropdown() {
      dropdown.classList.add('hidden');
      dropdown.innerHTML = '';
    }

    function showMessage(html) {
      dropdown.innerHTML = html;
      dropdown.classList.remove('hidden');
    }

    function renderLoading() {
      showMessage(
        '<div class="px-4 py-3 text-outline flex items-center gap-2">' +
        '<span class="material-symbols-outlined text-base animate-spin">progress_activity</span>' +
        'Searching…</div>'
      );
    }

    function groupHeader(label) {
      return (
        '<div class="px-4 pt-3 pb-1 text-xs font-semibold uppercase tracking-wide text-outline">' +
        escapeHtml(label) + '</div>'
      );
    }

    function courseRow(c) {
      const snippet = c.description
        ? '<div class="text-xs text-outline truncate">' + escapeHtml(truncate(c.description, 80)) + '</div>'
        : '';
      return (
        '<button type="button" class="gs-result w-full text-left px-4 py-2 hover:bg-surface-container-low focus:bg-surface-container-low focus:outline-none block" ' +
        'data-kind="course" ' +
        'data-course-id="' + escapeHtml(c.course_id) + '" ' +
        'data-path-id="' + escapeHtml(c.path_id) + '" ' +
        'data-path-type="' + escapeHtml(c.path_type) + '" ' +
        'data-lesson-id="' + escapeHtml(c.first_lesson_id == null ? '' : c.first_lesson_id) + '">' +
        '<div class="font-medium text-on-surface truncate">' + escapeHtml(c.title) + '</div>' +
        snippet +
        '</button>'
      );
    }

    function pathRow(p) {
      return (
        '<button type="button" class="gs-result w-full text-left px-4 py-2 hover:bg-surface-container-low focus:bg-surface-container-low focus:outline-none block" ' +
        'data-kind="path" ' +
        'data-path-id="' + escapeHtml(p.path_id) + '" ' +
        'data-path-type="' + escapeHtml(p.path_type) + '">' +
        '<div class="font-medium text-on-surface truncate">' + escapeHtml(p.title) + '</div>' +
        '</button>'
      );
    }

    function renderResults(data, query) {
      const courses = (data && data.courses) || [];
      const paths = (data && data.paths) || [];

      if (!courses.length && !paths.length) {
        showMessage(
          '<div class="px-4 py-3 text-outline">No results for “' + escapeHtml(query) + '”</div>'
        );
        return;
      }

      let html = '';
      if (courses.length) {
        html += groupHeader('Courses');
        html += courses.map(courseRow).join('');
      }
      if (paths.length) {
        html += groupHeader('Paths');
        html += paths.map(pathRow).join('');
      }
      dropdown.innerHTML = html;
      dropdown.classList.remove('hidden');
    }

    async function enroll(pathId, pathType) {
      const resp = await fetch(
        '/api/learning-path/' + encodeURIComponent(pathId) +
        '/enroll?path_type=' + encodeURIComponent(pathType || 'official') +
        '&user_id=' + currentUserId(),
        { method: 'POST' }
      );
      if (!resp.ok) throw new Error('enroll failed (' + resp.status + ')');
    }

    async function handleResultClick(btn) {
      if (btn.dataset.busy === '1') return;
      btn.dataset.busy = '1';
      btn.classList.add('opacity-60', 'pointer-events-none');
      const kind = btn.dataset.kind;
      const pathId = btn.dataset.pathId;
      const pathType = btn.dataset.pathType || 'official';
      try {
        await enroll(pathId, pathType);
        if (kind === 'course') {
          const courseId = btn.dataset.courseId;
          const lessonId = btn.dataset.lessonId;
          let url = '/lesson?course=' + encodeURIComponent(courseId);
          if (lessonId) url += '&lesson=' + encodeURIComponent(lessonId);
          window.location.href = url;
        } else {
          window.location.href = '/learning-path?path=' + encodeURIComponent(pathId);
        }
      } catch (err) {
        btn.classList.remove('opacity-60', 'pointer-events-none');
        btn.dataset.busy = '';
        const label = btn.querySelector('.font-medium');
        if (label) {
          const original = label.textContent;
          label.textContent = 'Error — try again';
          setTimeout(() => { label.textContent = original; }, 2500);
        }
      }
    }

    async function runSearch(query) {
      const requestId = ++activeRequestId;
      renderLoading();
      try {
        const resp = await fetch('/api/search?q=' + encodeURIComponent(query) + '&user_id=' + currentUserId());
        if (!resp.ok) throw new Error('search failed (' + resp.status + ')');
        const data = await resp.json();
        if (requestId !== activeRequestId) return; // a newer query superseded this one
        renderResults(data, query);
      } catch (err) {
        if (requestId !== activeRequestId) return;
        hideDropdown(); // non-critical feature: fail silently
      }
    }

    // ── Events ────────────────────────────────────────────────────────────────
    input.addEventListener('input', function () {
      const query = input.value.trim();
      if (debounceTimer) clearTimeout(debounceTimer);
      if (query.length < MIN_CHARS) {
        activeRequestId++; // invalidate any in-flight request
        hideDropdown();
        return;
      }
      debounceTimer = setTimeout(() => runSearch(query), DEBOUNCE_MS);
    });

    input.addEventListener('focus', function () {
      const query = input.value.trim();
      if (query.length >= MIN_CHARS && dropdown.innerHTML) {
        dropdown.classList.remove('hidden');
      }
    });

    dropdown.addEventListener('click', function (e) {
      const btn = e.target.closest('.gs-result');
      if (btn) handleResultClick(btn);
    });

    document.addEventListener('click', function (e) {
      if (!wrapper.contains(e.target)) hideDropdown();
    });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        hideDropdown();
        input.blur();
      }
    });
  });
})();
