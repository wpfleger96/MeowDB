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

    async playLeaderboardSound(sound) {
      if (!sound?.mp3_url) return;
      audioPlayer.stop();
      recordPlay(sound.id).catch(() => {});
      audioPlayer.onEnded = null;
      audioPlayer.onError = (err) => showToast('Playback error: ' + err.message, 'error');
      try {
        await audioPlayer.play(sound.mp3_url);
      } catch {}
    },

    get totalDurationFormatted() {
      return MeowUtils.formatDuration(this.stats?.total_duration_ms ?? null);
    },

    get avgDurationFormatted() {
      return MeowUtils.formatDuration(this.stats?.avg_duration_ms ?? null);
    },

    get firstSoundDate() {
      return this.stats?.first_sound_at
        ? MeowUtils.formatDate(this.stats.first_sound_at)
        : '—';
    },
  };
}
