/**
 * WisdomAI Shared Sidebar
 * =======================
 * Single source of truth for the left navigation sidebar across every page.
 *
 * Each page provides a `<div id="sidebar-mount"></div>` where the old
 * hand-copied <aside> used to live, plus a `sidebar-offset` class on the
 * elements that need to sit past the fixed sidebar (see Content offset below).
 *
 * Responsibilities:
 *   - Render the canonical sidebar (logo, nav links, Support, Settings).
 *   - Auto-detect the active link from window.location.pathname.
 *   - Desktop collapse/expand toggle (w-64 <-> w-20), persisted in localStorage.
 *   - Drive dynamic content offset via body.sidebar-expanded / .sidebar-collapsed.
 *   - Own the "Feature coming soon!" toast for Support/Settings.
 *   - Own the mobile hamburger (#mobile-menu-btn) show/hide behaviour.
 */
(function () {
  'use strict';

  // ── Canonical nav definition ────────────────────────────────────────────────
  const NAV_LINKS = [
    { href: '/', icon: 'dashboard', label: 'Dashboard' },
    { href: '/learning-path', icon: 'route', label: 'Learning Path', iconClass: 'rotate-90' },
    { href: '/knowledge-vault', icon: 'folder', label: 'Knowledge Vault' },
    { href: '/manager-dashboard', icon: 'groups', label: 'Team Dashboards' },
    { href: '/catalog', icon: 'menu_book', label: 'Catalog' },
  ];
  const SUPPORT_LINK = { icon: 'help', label: 'Support' };   // href="#" -> coming-soon toast
  const SETTINGS_LINK = { href: '/settings', icon: 'settings', label: 'Settings' };

  const LOGO_SRC = 'https://lh3.googleusercontent.com/aida-public/AB6AXuBLLiZQ4Ntu9A6ncb0b-E0Z2bUUjP3ezD1hhJPpUsyGV3wYannVJU77x55EdLqWY8dEPo17cpHoe6dep3b0fyEVpmT7UPiXW1JO3vETEUa9EvxG5QUbo4NLLJ2bbhHEoSYB4DYrjfSVNCBD6UjacfrxrrYZBk0Z6H5N55fBhjqDlny7miBSCajGdNDRfuNWAau1E77XKe3k9xxmCgWFU8xbaiU4s9013wpuMvUw71_gGZjrOzQ323xXMGCSLTM0UUe4lQ';

  const STORAGE_KEY = 'wai-sidebar-collapsed';
  const THEME_STORAGE_KEY = 'wai-theme';
  const ACTIVE_CLASSES = 'bg-secondary-container text-on-secondary-container rounded-xl font-bold translate-x-1 transition-transform duration-200';
  const INACTIVE_CLASSES = 'text-on-surface-variant hover:bg-surface-container-high rounded-xl transition-all';

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
  // Developers exclusively get the Agent Console, appended to their nav.
  const DEV_ONLY_LINK = { href: '/dev-console', icon: 'settings_suggest', label: 'Agent Console' };

  function visibleNavLinks() {
    const session = window.WisdomAuth && window.WisdomAuth.getSession();
    const role = session && session.role;
    var links = NAV_LINKS;
    if (role !== 'manager') {
      links = links.filter(function (l) { return MANAGER_ONLY_HREFS.indexOf(l.href) === -1; });
    }
    if (role === 'developer') {
      links = links.concat([DEV_ONLY_LINK]);
    }
    return links;
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
    const supportHtml = linkHtml(SUPPORT_LINK, { id: 'sidebar-support-link' });
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
      '#sidebar { transition: width .3s ease; }',
      '@media (min-width: 768px) {',
      '  body.sidebar-expanded  .sidebar-offset { margin-left: 16rem !important; }',
      '  body.sidebar-collapsed .sidebar-offset { margin-left: 5rem  !important; }',
      '  body.sidebar-expanded  .sidebar-offset-header { width: calc(100% - 16rem) !important; }',
      '  body.sidebar-collapsed .sidebar-offset-header { width: calc(100% - 5rem)  !important; }',
      '  .sidebar-offset, .sidebar-offset-header { transition: margin-left .3s ease, width .3s ease; }',
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

    const supportLink = document.getElementById('sidebar-support-link');
    if (supportLink) supportLink.addEventListener('click', function (e) {
      e.preventDefault();
      toast('Feature coming soon!');
    });

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
    applyState(isCollapsed());
    wireEvents();
    showAccessDeniedToastIfNeeded();
  }

  // Expose a tiny hook so pages can react after the sidebar is mounted.
  // applyTheme is exposed so other in-page controls (e.g. the Settings page's
  // own theme toggle) can flip the theme and keep this sidebar's button in sync.
  window.WisdomSidebar = { toast: toast, isActive: isActive, applyTheme: applyTheme, isDarkMode: isDarkMode };

  init();
})();
