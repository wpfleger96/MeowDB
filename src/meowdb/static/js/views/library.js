/* ============================================================
   views/library.js — Library Alpine component
   ============================================================ */

function libraryView() {
  return {
    meows: [],
    total: 0,
    offset: 0,
    limit: 50,
    sort: 'newest',
    filterLabel: '',
    allLabels: [],
    activeLabels: [],
    isLoading: false,
    isLoadingMore: false,
    playingId: null,

    // Detail modal state
    showDetail: false,
    detailMeow: null,
    showDeleteConfirm: false,
    labelInput: '',
    detailTitle: '',
    _detailIsPlaying: false,
    _cancelDetailWaveform: null,

    async init() {
      await Promise.all([
        this._loadMeows(true),
        this._loadLabels(),
      ]);
    },

    async _loadMeows(reset = false) {
      if (reset) {
        this.offset = 0;
        this.meows = [];
        this.isLoading = true;
      } else {
        this.isLoadingMore = true;
      }

      try {
        const params = {
          sort: this.sort,
          limit: this.limit,
          offset: this.offset,
        };
        if (this.filterLabel) params.label = this.filterLabel;

        const res = await getMeows(params);
        this.meows = reset ? res.items : [...this.meows, ...res.items];
        this.total = res.total;
        this.offset = this.meows.length;
      } catch (err) {
        showToast(err.message || 'Failed to load library', 'error');
      } finally {
        this.isLoading = false;
        this.isLoadingMore = false;
      }
    },

    async _loadLabels() {
      try {
        const labels = await getLabels();
        this.allLabels = labels;
      } catch {
        this.allLabels = [];
      }
    },

    async changeSort(newSort) {
      this.sort = newSort;
      await this._loadMeows(true);
    },

    async recalculate() {
      try {
        const result = await recalculateUniqueness({ force: true });
        showToast(`Uniqueness updated (${result.updated_count} fingerprints computed)`, 'success');
        await this._loadMeows(true);
      } catch (err) {
        showToast(err.message || 'Recalculation failed', 'error');
      }
    },

    async toggleLabelFilter(label) {
      if (this.filterLabel === label) {
        this.filterLabel = '';
      } else {
        this.filterLabel = label;
      }
      await this._loadMeows(true);
    },

    async loadMore() {
      if (this.isLoadingMore || this.meows.length >= this.total) return;
      await this._loadMeows(false);
    },

    get hasMore() {
      return this.meows.length < this.total;
    },

    /* ──────────────────────────────────────────────────────
       Inline playback
    ────────────────────────────────────────────────────── */

    async togglePlay(meow, event) {
      event.stopPropagation();

      if (this.playingId === meow.id) {
        audioPlayer.stop();
        this.playingId = null;
        return;
      }

      audioPlayer.stop();
      this.playingId = meow.id;

      // Record play (fire-and-forget)
      recordPlay(meow.id).catch(() => {});

      audioPlayer.onEnded = () => {
        if (this.playingId === meow.id) this.playingId = null;
      };
      audioPlayer.onError = () => {
        if (this.playingId === meow.id) this.playingId = null;
      };

      try {
        await audioPlayer.playWithFallback(meow.mp3_url, meow.wav_url);
      } catch {
        this.playingId = null;
      }
    },

    /* ──────────────────────────────────────────────────────
       Detail modal
    ────────────────────────────────────────────────────── */

    openDetail(meow) {
      audioPlayer.stop();
      this._stopDetailWaveform();
      this.playingId = null;
      this._detailIsPlaying = false;
      this.detailMeow = { ...meow, labels: [...(meow.labels || [])] };
      this.detailTitle = meow.title || '';
      this.showDetail = true;
      this.showDeleteConfirm = false;
      this.labelInput = '';

      // Draw static waveform after modal is in the DOM
      this.$nextTick(() => {
        this._drawDetailWaveform(meow, 0);
      });
    },

    closeDetail() {
      audioPlayer.stop();
      this._stopDetailWaveform();
      this._detailIsPlaying = false;
      this.showDetail = false;
      this.detailMeow = null;
      this.showDeleteConfirm = false;
    },

    _drawDetailWaveform(meow, progress) {
      const canvas = this.$refs.detailWaveformCanvas;
      if (!canvas || !meow?.waveform_data?.length) return;

      const color = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#ff6b6b';

      if (this._detailIsPlaying && progress === 0) {
        this._cancelDetailWaveform = animateWaveform(
          canvas,
          meow.waveform_data,
          color,
          () => {
            if (audioPlayer.duration === 0) return 0;
            return audioPlayer.currentTime / audioPlayer.duration;
          }
        );
      } else {
        drawWaveform(canvas, meow.waveform_data, color, progress);
      }
    },

    _stopDetailWaveform() {
      if (this._cancelDetailWaveform) {
        this._cancelDetailWaveform();
        this._cancelDetailWaveform = null;
      }
    },

    playDetailMeow() {
      if (this._detailIsPlaying) {
        audioPlayer.stop();
        this._stopDetailWaveform();
        this._detailIsPlaying = false;
        return;
      }

      const meow = this.detailMeow;
      if (!meow) return;

      this._detailIsPlaying = true;
      recordPlay(meow.id).catch(() => {});
      this._drawDetailWaveform(meow, 0);

      audioPlayer.onEnded = () => {
        this._detailIsPlaying = false;
        this._stopDetailWaveform();
        this._drawDetailWaveform(meow, 1);
      };
      audioPlayer.onError = () => {
        this._detailIsPlaying = false;
        this._stopDetailWaveform();
      };

      audioPlayer.playWithFallback(meow.mp3_url, meow.wav_url).catch(() => {
        this._detailIsPlaying = false;
        this._stopDetailWaveform();
      });
    },

    /* ──────────────────────────────────────────────────────
       Label editing
    ────────────────────────────────────────────────────── */

    removeLabel(label) {
      if (!this.detailMeow) return;
      if (this.$root.authRequired && !this.$root.authenticated) { this.$root.showLoginModal = true; return; }
      this.detailMeow.labels = this.detailMeow.labels.filter((l) => l !== label);
      this._saveLabels();
    },

    async addLabel() {
      const label = this.labelInput.trim().toLowerCase();
      if (!label || !this.detailMeow) return;
      if (this.detailMeow.labels.includes(label)) {
        this.labelInput = '';
        return;
      }
      if (this.$root.authRequired && !this.$root.authenticated) { this.$root.showLoginModal = true; return; }
      this.detailMeow.labels = [...this.detailMeow.labels, label];
      this.labelInput = '';
      await this._saveLabels();
    },

    async _saveLabels() {
      if (!this.detailMeow) return;
      if (this.$root.authRequired && !this.$root.authenticated) { this.$root.showLoginModal = true; return; }
      try {
        await updateLabels(this.detailMeow.id, this.detailMeow.labels);
        // Update the row in the list too
        const idx = this.meows.findIndex((m) => m.id === this.detailMeow.id);
        if (idx !== -1) {
          this.meows[idx] = { ...this.meows[idx], labels: [...this.detailMeow.labels] };
        }
        // Refresh label filter chips
        await this._loadLabels();
      } catch (err) {
        showToast(err.message || 'Failed to save labels', 'error');
      }
    },

    async saveTitle() {
      if (!this.detailMeow) return;
      if (this.$root.authRequired && !this.$root.authenticated) { this.$root.showLoginModal = true; return; }
      try {
        const updated = await updateMeow(this.detailMeow.id, { title: this.detailTitle || null });
        this.detailMeow = { ...updated, labels: updated.labels || [] };
        const idx = this.meows.findIndex((m) => m.id === this.detailMeow.id);
        if (idx !== -1) this.meows[idx] = { ...this.meows[idx], title: updated.title };
      } catch (err) {
        showToast(err.message || 'Failed to save title', 'error');
      }
    },

    /* ──────────────────────────────────────────────────────
       Delete
    ────────────────────────────────────────────────────── */

    confirmDelete() {
      this.showDeleteConfirm = true;
    },

    async deleteMeowConfirmed() {
      if (!this.detailMeow) return;
      if (this.$root.authRequired && !this.$root.authenticated) { this.$root.showLoginModal = true; return; }
      const id = this.detailMeow.id;
      try {
        await deleteMeow(id);
        this.meows = this.meows.filter((m) => m.id !== id);
        this.total = Math.max(0, this.total - 1);
        this.closeDetail();
        showToast('Meow deleted', 'success');
        // Refresh label counts
        await this._loadLabels();
      } catch (err) {
        showToast(err.message || 'Failed to delete', 'error');
      }
    },

    /* ──────────────────────────────────────────────────────
       Formatting helpers
    ────────────────────────────────────────────────────── */

    formatDuration(ms) { return MeowUtils.formatDuration(ms); },
    formatDate(iso) { return MeowUtils.formatDate(iso); },
    formatId(id) { return MeowUtils.formatId(id); },

    uniquenessBadgeClass(score) {
      if (score == null) return 'badge-default';
      if (score >= 75) return 'badge-green';
      if (score >= 50) return 'badge-yellow';
      return 'badge-red';
    },
  };
}
