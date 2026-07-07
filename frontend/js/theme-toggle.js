/**
 * WisdomAI Theme Toggle
 * ======================
 * Switches between light and dark mode by toggling the class on <html>.
 * Persists the user's preference in localStorage.
 */

(function () {
  const STORAGE_KEY = 'wisdomai-theme';

  function getPreferred() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function apply(theme) {
    const html = document.documentElement;
    html.classList.remove('light', 'dark');
    html.classList.add(theme);
    localStorage.setItem(STORAGE_KEY, theme);

    // Update any toggle buttons on the page
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      const icon = btn.querySelector('.material-symbols-outlined');
      if (icon) icon.textContent = theme === 'dark' ? 'light_mode' : 'dark_mode';
    });
  }

  function toggle() {
    const current = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    apply(current === 'dark' ? 'light' : 'dark');
  }

  // Apply on load
  apply(getPreferred());

  // Expose globally
  window.WisdomTheme = { toggle, apply };

  // Auto-bind any toggle buttons
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.addEventListener('click', toggle);
    });
  });
})();
