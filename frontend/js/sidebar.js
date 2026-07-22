/**
 * WisdomAI Shared Sidebar
 * =======================
 * Single source of truth for the left navigation sidebar across every page.
 *
 * Each page provides a `<div id="sidebar-mount"></div>` where the old
 * hand-copied <aside> used to live, plus a `sidebar-offset` class on the
 * elements that need to sit past the fixed sidebar (see Content offset below).
 * A page's header can also provide `<div id="header-avatar-mount"></div>` to
 * get the shared, session-driven initials avatar (links to /profile).
 *
 * Responsibilities:
 *   - Render the canonical sidebar (logo, nav links, Support, Settings).
 *   - Render the header avatar (see header-avatar-mount above).
 *   - Auto-detect the active link from window.location.pathname.
 *   - Desktop collapse/expand toggle (w-64 <-> w-20), persisted in localStorage.
 *   - Drive dynamic content offset via body.sidebar-expanded / .sidebar-collapsed.
 *   - Route Support by role (/support form vs /support-console queue).
 *   - Own the mobile hamburger (#mobile-menu-btn) show/hide behaviour.
 */
(function () {
  'use strict';

  // ── Canonical nav definition ────────────────────────────────────────────────
  // Order follows the natural learner flow: overview, then browse/enroll
  // (Catalog), then your assigned path, then shared reference material
  // (Knowledge Vault, Team Docs) — manager-only oversight (Team Dashboards)
  // comes last since it's an admin view, not part of an individual's path.
  const NAV_LINKS = [
    { href: '/', icon: 'dashboard', label: 'Dashboard' },
    { href: '/catalog', icon: 'menu_book', label: 'Catalog' },
    { href: '/learning-path', icon: 'route', label: 'Learning Path', iconClass: 'rotate-90' },
    { href: '/knowledge-vault', icon: 'folder', label: 'Knowledge Vault' },
    { href: '/team-documentation', icon: 'article', label: 'Team Docs' },
    { href: '/manager-dashboard', icon: 'groups', label: 'Team Dashboards' },
  ];
  const SETTINGS_LINK = { href: '/settings', icon: 'settings', label: 'Settings' };

  // Support is role-aware: the developer lands on the ticket queue console,
  // everyone else lands on the "report an issue" form.
  function supportLink() {
    const session = window.WisdomAuth && window.WisdomAuth.getSession();
    const href = session && session.role === 'developer' ? '/support-console' : '/support';
    return { href: href, icon: 'help', label: 'Support' };
  }

  const LOGO_SRC = 'https://lh3.googleusercontent.com/aida-public/AB6AXuBLLiZQ4Ntu9A6ncb0b-E0Z2bUUjP3ezD1hhJPpUsyGV3wYannVJU77x55EdLqWY8dEPo17cpHoe6dep3b0fyEVpmT7UPiXW1JO3vETEUa9EvxG5QUbo4NLLJ2bbhHEoSYB4DYrjfSVNCBD6UjacfrxrrYZBk0Z6H5N55fBhjqDlny7miBSCajGdNDRfuNWAau1E77XKe3k9xxmCgWFU8xbaiU4s9013wpuMvUw71_gGZjrOzQ323xXMGCSLTM0UUe4lQ';

  const STORAGE_KEY = 'wai-sidebar-collapsed';
  const THEME_STORAGE_KEY = 'wai-theme';
  const ACTIVE_CLASSES = 'bg-secondary-container text-on-secondary-container rounded-xl font-bold translate-x-1 transition-transform duration-200';
  const INACTIVE_CLASSES = 'text-on-surface-variant hover:bg-surface-container-high rounded-xl transition-all';

  // ── Background job notifications ────────────────────────────────────────────
  // Long-running server-side work (e.g. Team Docs AI drafting/generation) is
  // fire-and-forget from the browser's point of view: it returns a job_id
  // immediately and finishes on the server regardless of navigation. Pending
  // job IDs and finished notifications live in localStorage (not page state)
  // specifically so that whichever page happens to be open when a job
  // finishes — not necessarily the one that started it — is the one that
  // notices and surfaces it; a full reload/navigation never loses track of it.
  const PENDING_JOBS_KEY = 'wai-pending-jobs';
  const NOTIFICATIONS_KEY = 'wai-notifications';
  const JOB_POLL_MS = 4000;
  const MAX_NOTIFICATIONS = 20;

  // Where to poll a job's status, keyed by the `kind` the caller registers it
  // with. Add an entry here for each new background-job subsystem.
  const JOB_STATUS_URL = {
    team_docs_ai_draft: function (job) { return '/api/team-docs/jobs/' + job.job_id + '?department=' + encodeURIComponent(job.department); },
    team_docs_generate: function (job) { return '/api/team-docs/jobs/' + job.job_id + '?department=' + encodeURIComponent(job.department); },
  };

  function readJSON(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function writeJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage unavailable */ }
  }

  function getPendingJobs() { return readJSON(PENDING_JOBS_KEY, []); }
  function getNotifications() { return readJSON(NOTIFICATIONS_KEY, []); }

  // A job that can never resolve (server restart wiped it, a typo'd job_id,
  // etc.) would otherwise poll every JOB_POLL_MS forever — cap how long
  // we'll keep trying before quietly giving up on it.
  const JOB_MAX_AGE_MS = 30 * 60 * 1000;

  function trackJob(job) {
    // job: { job_id, kind, department }
    const pending = getPendingJobs();
    if (pending.some(function (j) { return j.job_id === job.job_id; })) return;
    job = Object.assign({ started_at: Date.now() }, job);
    pending.push(job);
    writeJSON(PENDING_JOBS_KEY, pending);
    schedulePoll(0);
  }

  function addNotification(message) {
    const notifications = getNotifications();
    notifications.unshift({ id: 'n_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7), message: message, timestamp: new Date().toISOString(), seen: false });
    writeJSON(NOTIFICATIONS_KEY, notifications.slice(0, MAX_NOTIFICATIONS));
    renderNotifBell();
  }

  function unseenNotificationCount() {
    return getNotifications().filter(function (n) { return !n.seen; }).length;
  }

  function markAllNotificationsSeen() {
    const notifications = getNotifications().map(function (n) { return Object.assign({}, n, { seen: true }); });
    writeJSON(NOTIFICATIONS_KEY, notifications);
    renderNotifBell();
  }

  let pollTimer = null;
  function schedulePoll(delay) {
    if (pollTimer) clearTimeout(pollTimer);
    if (getPendingJobs().length === 0) return;
    pollTimer = setTimeout(pollPendingJobs, delay == null ? JOB_POLL_MS : delay);
  }

  function pollPendingJobs() {
    const pending = getPendingJobs();
    if (pending.length === 0) return;
    Promise.all(pending.map(function (job) {
      const urlFn = JOB_STATUS_URL[job.kind];
      if (!urlFn) return null; // unknown kind — drop it rather than poll forever
      return fetch(urlFn(job)).then(function (res) {
        if (!res.ok) return null; // 404s etc. — leave it pending and retry later
        return res.json().then(function (data) { return { job: job, data: data }; });
      }).catch(function () { return null; });
    })).then(function (results) {
      let remaining = getPendingJobs();
      results.forEach(function (result) {
        if (!result) return;
        const status = result.data.status;
        if (status !== 'completed' && status !== 'error') return; // still processing
        remaining = remaining.filter(function (j) { return j.job_id !== result.job.job_id; });
        if (status === 'completed') {
          addNotification(result.data.message || 'Background task finished.');
          toast(result.data.message || 'Background task finished.');
        } else {
          addNotification(result.data.message || 'Background task failed.');
          toast(result.data.message || 'Background task failed.', 'warn');
        }
        window.dispatchEvent(new CustomEvent('wai:job-done', { detail: Object.assign({ job_id: result.job.job_id }, result.data) }));
      });
      // Give up quietly on anything that's been unresolvable for too long
      // (a wrong job_id, a job the server no longer knows about, etc.) so a
      // single bad entry can't poll forever.
      const now = Date.now();
      remaining = remaining.filter(function (j) { return now - (j.started_at || 0) < JOB_MAX_AGE_MS; });
      writeJSON(PENDING_JOBS_KEY, remaining);
      schedulePoll();
    });
  }

  function formatNotifTime(isoString) {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const mins = Math.round(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hours = Math.round(mins / 60);
    if (hours < 24) return hours + 'h ago';
    return Math.round(hours / 24) + 'd ago';
  }

  function notifBellHtml() {
    const count = unseenNotificationCount();
    const badge = count > 0
      ? '<span id="wai-notif-badge" class="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-error text-on-error text-[10px] font-bold flex items-center justify-center leading-none">' + count + '</span>'
      : '';
    return (
      '<div class="relative">' +
        '<button id="wai-notif-bell" type="button" aria-label="Notifications" title="Notifications" ' +
          'class="w-10 h-10 rounded-full flex items-center justify-center text-on-surface-variant hover:bg-surface-container-high transition-colors relative flex-shrink-0">' +
          '<span class="material-symbols-outlined">notifications</span>' +
          badge +
        '</button>' +
        '<div id="wai-notif-panel" class="hidden absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto bg-surface-container-lowest border border-outline-variant rounded-xl shadow-lg z-50"></div>' +
      '</div>'
    );
  }

  function renderNotifPanelContents() {
    const panel = document.getElementById('wai-notif-panel');
    if (!panel) return;
    const notifications = getNotifications();
    panel.innerHTML = notifications.length
      ? notifications.map(function (n) {
          return (
            '<div class="px-4 py-3 border-b border-outline-variant last:border-0' + (n.seen ? ' opacity-70' : '') + '">' +
              '<p class="text-sm text-on-surface">' + n.message + '</p>' +
              '<p class="text-xs text-on-surface-variant mt-1">' + formatNotifTime(n.timestamp) + '</p>' +
            '</div>'
          );
        }).join('')
      : '<div class="px-4 py-6 text-sm text-on-surface-variant text-center">No notifications yet.</div>';
  }

  // Re-render just the bell (badge count) without disturbing an open panel's
  // scroll position — called whenever notifications change.
  function renderNotifBell() {
    const mount = document.getElementById('wai-notif-mount');
    if (!mount) return;
    const wasOpen = !document.getElementById('wai-notif-panel').classList.contains('hidden');
    mount.innerHTML = notifBellHtml();
    wireNotifBell();
    if (wasOpen) {
      document.getElementById('wai-notif-panel').classList.remove('hidden');
      renderNotifPanelContents();
    }
  }

  function wireNotifBell() {
    const bell = document.getElementById('wai-notif-bell');
    const panel = document.getElementById('wai-notif-panel');
    if (!bell || !panel) return;
    bell.addEventListener('click', function (e) {
      e.stopPropagation();
      const opening = panel.classList.contains('hidden');
      panel.classList.toggle('hidden');
      if (opening) {
        renderNotifPanelContents();
        markAllNotificationsSeen();
      }
    });
    document.addEventListener('click', function (e) {
      if (!panel.classList.contains('hidden') && !panel.contains(e.target) && e.target !== bell) {
        panel.classList.add('hidden');
      }
    });
  }

  // ── Wisdom AI chat launcher (floating button, bottom-right) ────────────────
  // Hidden on the chat page itself (redundant there) and on quiz/assessment
  // pages, where an incoming chat message would distract from the assessment.
  const CHAT_LAUNCHER_EXCLUDED_PATHS = ['/chat', '/quiz'];

  function mountChatLauncher() {
    if (document.getElementById('wai-chat-launcher')) return;
    if (!(window.WisdomAuth && window.WisdomAuth.getSession())) return;
    let path = window.location.pathname;
    if (path.length > 1) path = path.replace(/\/+$/, '');
    if (CHAT_LAUNCHER_EXCLUDED_PATHS.indexOf(path) !== -1) return;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = (
      '<a href="/chat" id="wai-chat-launcher" aria-label="Open Wisdom AI chat" title="Wisdom AI Chat" ' +
        'class="fixed bottom-24 right-6 md:bottom-6 z-40 w-14 h-14 rounded-full bg-primary text-on-primary ' +
        'flex items-center justify-center shadow-lg hover:scale-105 transition-transform">' +
        '<span class="material-symbols-outlined text-3xl">forum</span>' +
      '</a>'
    );
    document.body.appendChild(wrapper.firstElementChild);
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function isCollapsed() {
    return localStorage.getItem(STORAGE_KEY) === 'true';
  }

  // The blocking inline script in each page's <head> already applied the
  // 'dark' class before this file runs (avoids a light->dark flash), so this
  // just reads that resulting state rather than re-deciding it.
  function isDarkMode() {
    return document.documentElement.classList.contains('dark');
  }

  // Exact-match active detection. '/' matches ONLY the root path, never as a prefix.
  function isActive(href) {
    let path = window.location.pathname;
    if (path.length > 1) path = path.replace(/\/+$/, ''); // strip trailing slash (but keep bare '/')
    if (path === '') path = '/';
    if (href === '/') return path === '/';
    return path === href;
  }

  function linkHtml(link, opts) {
    opts = opts || {};
    const cls = opts.active ? ACTIVE_CLASSES : INACTIVE_CLASSES;
    const iconCls = link.iconClass ? ' ' + link.iconClass : '';
    const idAttr = opts.id ? ' id="' + opts.id + '"' : '';
    const href = link.href || '#';
    return (
      '<a' + idAttr + ' class="sidebar-nav-link flex items-center gap-3 px-4 py-3 ' + cls + '" href="' + href + '">' +
        '<span class="material-symbols-outlined' + iconCls + '">' + link.icon + '</span>' +
        '<span class="sidebar-label font-label-md text-label-md">' + link.label + '</span>' +
      '</a>'
    );
  }

  // Employees and developers never see the manager-only tools. Managers see everything.
  const MANAGER_ONLY_HREFS = ['/manager-dashboard', '/knowledge-vault'];
  // Team Docs belongs to the manager/employee side; developers have their own docs.
  const TEAM_ONLY_HREFS = ['/team-documentation'];
  // Developers exclusively get the Agent Console, Documentation and UAT Console.
  const DEV_ONLY_LINK = { href: '/dev-console', icon: 'settings_suggest', label: 'Agent Console' };
  const DOCS_LINK = { href: '/documentation', icon: 'description', label: 'Documentation' };
  const UAT_LINK = { href: '/qa-console', icon: 'checklist', label: 'UAT Console' };

  function visibleNavLinks() {
    const session = window.WisdomAuth && window.WisdomAuth.getSession();
    const role = session && session.role;
    var links = NAV_LINKS;
    if (role !== 'manager') {
      links = links.filter(function (l) { return MANAGER_ONLY_HREFS.indexOf(l.href) === -1; });
    }
    if (role === 'developer') {
      links = links.filter(function (l) { return TEAM_ONLY_HREFS.indexOf(l.href) === -1; });
      links = links.concat([DEV_ONLY_LINK, DOCS_LINK, UAT_LINK]);
    }
    return links;
  }

  // First letter of the first two words of a display name, e.g. "Alex Chen" -> "AC".
  function initials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1] ? parts[1][0] : '')).toUpperCase();
  }

  // Single source of truth for the header avatar: a session-driven initials
  // circle linking to /profile. Previously every page hand-copied its own
  // <img src="https://..."> here -- five different hardcoded stock photos
  // unrelated to whoever was actually logged in, and clickable on only 2 of
  // the 10 pages that had one. Pages opt in with <div id="header-avatar-mount">.
  function headerAvatarHtml() {
    const session = window.WisdomAuth && window.WisdomAuth.getSession();
    const name = session ? session.display_name : '';
    return (
      '<a href="/profile" id="header-avatar-btn" aria-label="View profile" title="' + (name || 'Profile') + '" ' +
        'class="w-10 h-10 rounded-full bg-primary text-on-primary flex items-center justify-center font-bold text-sm flex-shrink-0 hover:opacity-90 transition-opacity">' +
        initials(name) +
      '</a>'
    );
  }

  function accountHtml() {
    const session = window.WisdomAuth && window.WisdomAuth.getSession();
    if (!session) return '';
    const roleLabel = session.role === 'manager' ? 'Manager' : (session.role === 'developer' ? 'Developer' : 'Employee');
    return (
      '<div class="px-4 py-3 rounded-xl bg-surface-container-high mb-1">' +
        '<div class="font-label-md text-label-md text-on-surface truncate">' + session.display_name + '</div>' +
        '<div class="text-xs text-on-surface-variant mb-2">' + roleLabel + '</div>' +
        '<button id="sidebar-logout-link" type="button" ' +
          'class="flex items-center gap-2 text-xs font-bold text-primary hover:underline">' +
          '<span class="material-symbols-outlined text-[16px]">logout</span> Log out' +
        '</button>' +
      '</div>'
    );
  }

  function renderSidebarHtml() {
    const navLinks = visibleNavLinks().map(function (l) {
      return linkHtml(l, { active: isActive(l.href) });
    }).join('');
    const support = supportLink();
    const supportHtml = linkHtml(support, { id: 'sidebar-support-link', active: isActive(support.href) });
    const settingsHtml = linkHtml(SETTINGS_LINK, { id: 'sidebar-settings-link', active: isActive(SETTINGS_LINK.href) });
    const themeToggleHtml = (
      '<button id="sidebar-theme-toggle" type="button" ' +
        'class="sidebar-nav-link flex items-center gap-3 px-4 py-3 w-full text-left ' + INACTIVE_CLASSES + '">' +
        '<span class="material-symbols-outlined">' + (isDarkMode() ? 'light_mode' : 'dark_mode') + '</span>' +
        '<span class="sidebar-label font-label-md text-label-md">' + (isDarkMode() ? 'Light mode' : 'Dark mode') + '</span>' +
      '</button>'
    );

    return (
      '<aside id="sidebar" class="hidden md:flex flex-col h-full py-6 px-4 fixed left-0 top-0 w-64 border-r border-outline-variant bg-surface-container-low z-40 min-h-screen">' +
        '<div class="sidebar-logo-row mb-10 px-2 flex items-center gap-2">' +
          '<img alt="WisdomAI Logo" class="w-8 h-8 flex-shrink-0 object-contain" src="' + LOGO_SRC + '">' +
          '<span class="sidebar-wordmark font-headline-md text-headline-md font-extrabold text-primary">WisdomAI</span>' +
          '<button id="sidebar-collapse-btn" type="button" aria-label="Collapse sidebar" ' +
            'class="sidebar-collapse-btn hidden md:flex items-center justify-center ml-auto w-8 h-8 rounded-lg text-on-surface-variant hover:bg-surface-container-high transition-colors">' +
            '<span class="material-symbols-outlined text-[20px]">chevron_left</span>' +
          '</button>' +
        '</div>' +
        '<nav class="sidebar-nav flex-1 space-y-1">' + navLinks + supportHtml + '</nav>' +
        '<div class="mt-auto pt-6 border-t border-outline-variant">' +
          '<div class="space-y-1">' + accountHtml() + themeToggleHtml + settingsHtml + '</div>' +
        '</div>' +
      '</aside>'
    );
  }

  function applyTheme(dark) {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem(THEME_STORAGE_KEY, dark ? 'dark' : 'light');
    const btn = document.getElementById('sidebar-theme-toggle');
    if (!btn) return;
    const icon = btn.querySelector('.material-symbols-outlined');
    const label = btn.querySelector('.sidebar-label');
    if (icon) icon.textContent = dark ? 'light_mode' : 'dark_mode';
    if (label) label.textContent = dark ? 'Light mode' : 'Dark mode';
  }

  // ── Content offset + collapse CSS (injected once) ───────────────────────────
  function injectStyles() {
    if (document.getElementById('wai-sidebar-styles')) return;
    const style = document.createElement('style');
    style.id = 'wai-sidebar-styles';
    style.textContent = [
      // Transitions start OFF so the very first state application on page
      // load (below, in init()) snaps straight into place instead of
      // animating -- every full page navigation re-mounts this component
      // from scratch, and without this guard the header/search bar would
      // visibly slide into its offset position on every single transition,
      // looking like the sidebar re-opens each time. 'sidebar-ready' is only
      // added a frame later, so real user-triggered collapse/expand clicks
      // still animate normally.
      '#sidebar { transition: none; }',
      'body.sidebar-ready #sidebar { transition: width .3s ease; }',
      '.sidebar-offset, .sidebar-offset-header { transition: none; }',
      'body.sidebar-ready .sidebar-offset, body.sidebar-ready .sidebar-offset-header { transition: margin-left .3s ease, width .3s ease; }',
      '@media (min-width: 768px) {',
      '  body.sidebar-expanded  .sidebar-offset { margin-left: 16rem !important; }',
      '  body.sidebar-collapsed .sidebar-offset { margin-left: 5rem  !important; }',
      '  body.sidebar-expanded  .sidebar-offset-header { width: calc(100% - 16rem) !important; }',
      '  body.sidebar-collapsed .sidebar-offset-header { width: calc(100% - 5rem)  !important; }',
      '  #sidebar.is-collapsed .sidebar-label { display: none; }',
      '  #sidebar.is-collapsed .sidebar-wordmark { display: none; }',
      '  #sidebar.is-collapsed .sidebar-collapse-btn { margin-left: 0; }',
      '  #sidebar.is-collapsed .sidebar-nav-link { justify-content: center; padding-left: 0; padding-right: 0; }',
      '  #sidebar.is-collapsed .sidebar-logo-row { flex-direction: column; justify-content: center; gap: .5rem; }',
      '  #sidebar.is-collapsed .sidebar-logo-row img { margin-right: 0; }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  }

  // ── Apply collapsed / expanded state ────────────────────────────────────────
  function applyState(collapsed) {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    document.body.classList.toggle('sidebar-expanded', !collapsed);

    const aside = document.getElementById('sidebar');
    if (aside) {
      aside.classList.toggle('is-collapsed', collapsed);
      aside.classList.toggle('md:w-20', collapsed);   // desktop icon-only width (mobile stays w-64)
      const btn = document.getElementById('sidebar-collapse-btn');
      if (btn) {
        const icon = btn.querySelector('.material-symbols-outlined');
        if (icon) icon.textContent = collapsed ? 'chevron_right' : 'chevron_left';
        btn.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
      }
    }
  }

  // ── Toast (ports dashboard.html's exact style; reuses page's if present) ─────
  function toast(message, type) {
    if (typeof window.showToast === 'function') { window.showToast(message, type); return; }
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'fixed bottom-6 left-1/2 -translate-x-1/2 z-[999] flex flex-col gap-2 pointer-events-none';
      document.body.appendChild(container);
    }
    const colors = { info: 'bg-primary text-on-primary', warn: 'bg-error-container text-on-error-container' };
    const t = document.createElement('div');
    t.className = 'px-5 py-3 rounded-lg shadow-lg font-bold text-sm pointer-events-auto transition-all duration-300 opacity-0 translate-y-2 ' + (colors[type] || colors.info);
    t.textContent = message;
    container.appendChild(t);
    requestAnimationFrame(function () { t.classList.remove('opacity-0', 'translate-y-2'); });
    setTimeout(function () {
      t.classList.add('opacity-0', 'translate-y-2');
      setTimeout(function () { t.remove(); }, 300);
    }, 3000);
  }

  // ── Wire interactions ───────────────────────────────────────────────────────
  function wireEvents() {
    const collapseBtn = document.getElementById('sidebar-collapse-btn');
    if (collapseBtn) {
      collapseBtn.addEventListener('click', function () {
        const next = !isCollapsed();
        localStorage.setItem(STORAGE_KEY, String(next));
        applyState(next);
      });
    }

    const themeToggle = document.getElementById('sidebar-theme-toggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', function () {
        applyTheme(!isDarkMode());
      });
    }

    const logoutLink = document.getElementById('sidebar-logout-link');
    if (logoutLink) logoutLink.addEventListener('click', function () {
      if (window.WisdomAuth) window.WisdomAuth.logout();
    });

    // Centralised mobile show/hide: any page's #mobile-menu-btn toggles the aside.
    const aside = document.getElementById('sidebar');
    const mobileBtn = document.getElementById('mobile-menu-btn');
    if (aside && mobileBtn) {
      mobileBtn.addEventListener('click', function () {
        aside.classList.toggle('hidden');
        aside.classList.toggle('flex');
      });
    }
  }

  // If auth.js's requireRole() just redirected here for lacking a role,
  // explain why instead of silently landing the user back on their dashboard.
  function showAccessDeniedToastIfNeeded() {
    const params = new URLSearchParams(window.location.search);
    const denied = params.get('denied');
    if (!denied) return;
    toast("You don't have " + denied + " access for that page.", 'warn');
    params.delete('denied');
    const query = params.toString();
    const url = window.location.pathname + (query ? '?' + query : '') + window.location.hash;
    window.history.replaceState({}, '', url);
  }

  // ── Init (runs synchronously at script position; #sidebar-mount is above it) ─
  function init() {
    injectStyles();
    const mount = document.getElementById('sidebar-mount');
    if (mount) mount.innerHTML = renderSidebarHtml();
    const avatarMount = document.getElementById('header-avatar-mount');
    if (avatarMount) {
      avatarMount.innerHTML = '<div class="flex items-center gap-2"><div id="wai-notif-mount">' + notifBellHtml() + '</div>' + headerAvatarHtml() + '</div>';
      wireNotifBell();
    }
    mountChatLauncher();
    applyState(isCollapsed());
    wireEvents();
    showAccessDeniedToastIfNeeded();
    schedulePoll(0);
    // Wait a frame (two, to be safe against browsers batching the first
    // paint) before allowing transitions, so the initial mount never animates.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        document.body.classList.add('sidebar-ready');
      });
    });
  }

  // Expose a tiny hook so pages can react after the sidebar is mounted.
  // applyTheme is exposed so other in-page controls (e.g. the Settings page's
  // own theme toggle) can flip the theme and keep this sidebar's button in sync.
  // initials is exposed so Profile/Settings can render the same avatar math
  // instead of re-deriving it (see headerAvatarHtml above for the header copy).
  // trackJob(job) lets any page register a background job ({job_id, kind,
  // department}) for the persistent notification system to poll — see the
  // "Background job notifications" section above for why this lives here
  // instead of in the page that started the job.
  window.WisdomSidebar = { toast: toast, isActive: isActive, applyTheme: applyTheme, isDarkMode: isDarkMode, initials: initials, trackJob: trackJob };

  init();
})();
