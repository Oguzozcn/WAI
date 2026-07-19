/**
 * WisdomAI Auth
 * =============
 * Minimal per-tab session for the manager/employee login simulation.
 *
 * Session is stored in sessionStorage (NOT localStorage) so that separate
 * browser tabs can be logged in as different accounts at the same time —
 * required for the manager + 2 employees simultaneous-tabs workflow.
 *
 * Loaded on every page via <script src="/js/auth.js"></script>, before
 * sidebar.js and any page-specific script that needs the current user.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'wai-session';

  function getSession() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_e) {
      return null;
    }
  }

  function setSession(session) {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  }

  async function login(userId, password) {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, password: password }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'Login failed.');
    }
    const session = await resp.json();
    setSession(session);
    return session;
  }

  function logout() {
    sessionStorage.removeItem(STORAGE_KEY);
    window.location.href = '/login';
  }

  // Redirects to /login if no session exists. Call at the top of every
  // protected page. Returns the session (or null, after redirecting).
  function requireAuth() {
    const session = getSession();
    if (!session) {
      window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
      return null;
    }
    return session;
  }

  // Redirects non-managers to the personal dashboard. Call in addition to
  // requireAuth() at the top of manager-only pages.
  function requireRole(role) {
    const session = requireAuth();
    if (session && session.role !== role) {
      window.location.href = '/';
      return null;
    }
    return session;
  }

  window.WisdomAuth = { login, logout, getSession, requireAuth, requireRole };
})();
