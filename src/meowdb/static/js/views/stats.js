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

    get totalDurationFormatted() {
      return MeowUtils.formatDuration(this.stats?.total_duration_ms ?? null);
    },

    get avgDurationFormatted() {
      return MeowUtils.formatDuration(this.stats?.avg_duration_ms ?? null);
    },

    get firstMeowDate() {
      if (!this.stats?.recent?.length) return '—';
      return this.stats.first_meow_at
        ? MeowUtils.formatDate(this.stats.first_meow_at)
        : '—';
    },
  };
}
