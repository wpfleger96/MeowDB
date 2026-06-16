/* ============================================================
   views/stats.js — Stats dashboard Alpine component
   ============================================================ */

function statsView() {
  return {
    stats: null,
    isLoading: false,
    error: null,

    async init() {
      await this.load();
    },

    async load() {
      this.isLoading = true;
      this.error = null;
      // Recompute uniqueness scores in the background whenever stats are refreshed
      recalculateUniqueness().catch(() => {});
      try {
        this.stats = await getStats();
      } catch (err) {
        this.error = err.message || 'Failed to load stats';
        showToast(this.error, 'error');
      } finally {
        this.isLoading = false;
      }
    },

    async playLeaderboardMeow(meow) {
      if (!meow?.mp3_url) return;
      audioPlayer.stop();
      recordPlay(meow.id).catch(() => {});
      audioPlayer.onEnded = null;
      audioPlayer.onError = (err) => showToast('Playback error: ' + err.message, 'error');
      try {
        await audioPlayer.play(meow.mp3_url);
      } catch {}
    },

    /* ──────────────────────────────────────────────────────
       Formatting helpers
    ────────────────────────────────────────────────────── */

    formatDuration(ms) { return MeowUtils.formatDuration(ms); },
    formatDate(iso) { return MeowUtils.formatDate(iso); },
    formatId(id) { return MeowUtils.formatId(id); },

    get totalDurationFormatted() {
      return this.formatDuration(this.stats?.total_duration_ms ?? null);
    },

    get avgDurationFormatted() {
      return this.formatDuration(this.stats?.avg_duration_ms ?? null);
    },

    get firstMeowDate() {
      if (!this.stats?.recent?.length) return '—';
      // Most-recent is first in the list; iterate to find oldest via created_at
      // The API returns last 10, so we rely on the backend for "first" date
      // If the backend exposes it directly, use it; otherwise fall back.
      return this.stats.first_meow_at
        ? this.formatDate(this.stats.first_meow_at)
        : '—';
    },
  };
}
