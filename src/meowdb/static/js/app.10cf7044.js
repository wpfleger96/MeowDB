/* ============================================================
   app.js — client-side router, Alpine registrations, global state
   ============================================================ */

/* ──────────────────────────────────────────────────────────
   Route table
────────────────────────────────────────────────────────── */

const ROUTES = {
  '/':        'play',
  '/library': 'library',
  '/photos':  'photos',
  '/upload':  'ingest',
  '/stats':   'stats',
};

function pathToView(path) {
  return ROUTES[path] || ROUTES['/'];
}

/* ──────────────────────────────────────────────────────────
   Global navigation helper (called by view components)
────────────────────────────────────────────────────────── */

function navigateTo(path) {
  history.pushState({}, '', path);
  dispatchRouteChange(path);
}

function dispatchRouteChange(path) {
  window.dispatchEvent(new CustomEvent('route-change', { detail: { path } }));
}

/* ──────────────────────────────────────────────────────────
   Toast system
────────────────────────────────────────────────────────── */

/**
 * Show a transient toast notification.
 * @param {string} message
 * @param {'info'|'success'|'error'} [type='info']
 * @param {number} [duration=3000]
 */
function showToast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);

  setTimeout(() => {
    el.classList.add('removing');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }, duration);
}

/* ──────────────────────────────────────────────────────────
   Root Alpine component
────────────────────────────────────────────────────────── */

function app() {
  return {
    currentView: pathToView(location.pathname),
    authenticated: false,
    authRequired: false,
    showLoginModal: false,
    loginPassword: '',
    loginError: '',
    loginLoading: false,

    get canWrite() {
      return !this.authRequired || this.authenticated;
    },

    requireAuth() {
      if (!this.canWrite) {
        this.showLoginModal = true;
        return false;
      }
      return true;
    },

    async init() {
      // Handle browser back/forward
      window.addEventListener('popstate', () => {
        this.currentView = pathToView(location.pathname);
      });

      // Handle programmatic navigation
      window.addEventListener('route-change', (e) => {
        this.currentView = pathToView(e.detail.path);
      });

      window.addEventListener('auth-expired', () => {
        this.authenticated = false;
        this.showLoginModal = true;
        this.loginError = '';
      });

      try {
        const s = await getAuthStatus();
        this.authenticated = s.authenticated;
        this.authRequired = s.auth_required;
      } catch (_) {
        // auth status check is best-effort; if it fails, assume unauthenticated
      }

      if (this.authRequired && !this.authenticated && this.currentView === 'ingest') {
        navigateTo('/');
      }
    },

    isView(name) {
      return this.currentView === name;
    },

    goTo(path) {
      navigateTo(path);
    },

    navClass(view) {
      return this.currentView === view ? 'nav-tab active' : 'nav-tab';
    },

    async doLogin() {
      this.loginLoading = true;
      this.loginError = '';
      try {
        await login(this.loginPassword);
        this.authenticated = true;
        this.showLoginModal = false;
      } catch (e) {
        this.loginError = e.message === 'Authentication not configured'
          ? 'Login is currently unavailable'
          : (e.message || 'Login failed');
      } finally {
        this.loginPassword = '';
        this.loginLoading = false;
      }
    },

    async doLogout() {
      try {
        await logout();
      } catch (_) {}
      this.authenticated = false;
      this.loginError = '';
      if (this.authRequired) {
        navigateTo('/');
      }
    },
  };
}

/* ──────────────────────────────────────────────────────────
   Alpine registrations — called after Alpine is ready
────────────────────────────────────────────────────────── */

document.addEventListener('alpine:init', () => {
  Alpine.data('app', app);
  Alpine.data('playView', playView);
  Alpine.data('libraryView', libraryView);
  Alpine.data('photosView', photosView);
  Alpine.data('ingestView', ingestView);
  Alpine.data('statsView', statsView);
});
