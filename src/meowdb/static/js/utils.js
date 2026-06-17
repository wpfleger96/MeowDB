/* ============================================================
   utils.js — Shared formatting utilities
   ============================================================ */

window.MeowUtils = {
  formatDuration(ms) {
    if (!ms && ms !== 0) return '—';
    const totalSeconds = Math.round(ms / 1000);
    if (totalSeconds < 60) return `${totalSeconds}s`;
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return rm > 0 ? `${h}h ${rm}m` : `${h}h`;
  },

  formatDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  },

  formatId(id) {
    if (!id) return '';
    return id.slice(0, 8);
  },
};
