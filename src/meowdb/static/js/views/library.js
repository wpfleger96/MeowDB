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
    _wavesurfer: null,
    _wavesurferLoaded: false,

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

    async openDetail(meow) {
      audioPlayer.stop();
      this.playingId = null;
      this.detailMeow = { ...meow, labels: [...(meow.labels || [])] };
      this.detailTitle = meow.title || '';
      this.showDetail = true;
      this.showDeleteConfirm = false;
      this.labelInput = '';

      // Lazy-load WaveSurfer the first time a detail modal opens
      await this._ensureWaveSurfer();

      // Defer waveform init to next tick so the modal is in the DOM
      this.$nextTick(() => {
        this._initWaveSurfer(meow.mp3_url);
      });
    },

    closeDetail() {
      this._destroyWaveSurfer();
      this.showDetail = false;
      this.detailMeow = null;
      this.showDeleteConfirm = false;
    },

    async _ensureWaveSurfer() {
      if (this._wavesurferLoaded) return;
      if (typeof WaveSurfer !== 'undefined') {
        this._wavesurferLoaded = true;
        return;
      }
      // Lazy-load via dynamic script tag
      await new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = '/static/vendor/wavesurfer.min.js';
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
      this._wavesurferLoaded = true;
    },

    _initWaveSurfer(url) {
      const container = document.getElementById('wavesurfer-container');
      if (!container || typeof WaveSurfer === 'undefined') return;

      this._destroyWaveSurfer();

      this._wavesurfer = WaveSurfer.create({
        container,
        waveColor: 'var(--border-strong)',
        progressColor: 'var(--accent)',
        cursorColor: 'transparent',
        barWidth: 3,
        barRadius: 2,
        barGap: 2,
        height: 80,
        normalize: true,
        interact: true,
        url,
      });
    },

    _destroyWaveSurfer() {
      if (this._wavesurfer) {
        try { this._wavesurfer.destroy(); } catch {}
        this._wavesurfer = null;
      }
    },

    playDetailMeow() {
      if (this._wavesurfer) {
        this._wavesurfer.playPause();
      }
    },

    /* ──────────────────────────────────────────────────────
       Label editing
    ────────────────────────────────────────────────────── */

    removeLabel(label) {
      if (!this.detailMeow) return;
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
      this.detailMeow.labels = [...this.detailMeow.labels, label];
      this.labelInput = '';
      await this._saveLabels();
    },

    async _saveLabels() {
      if (!this.detailMeow) return;
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
  };
}
