/* ============================================================
   views/library.js — Library Alpine component
   ============================================================ */

function libraryView() {
  return {
    sounds: [],
    total: 0,
    offset: 0,
    limit: 50,
    sort: 'newest',
    filterLabel: '',
    filterAnimal: '',
    allLabels: [],
    animals: [],
    activeLabels: [],
    isLoading: false,
    isLoadingMore: false,
    playingId: null,

    // Detail modal state
    showDetail: false,
    detailSound: null,
    showDeleteConfirm: false,
    labelInput: '',
    detailTitle: '',
    _detailIsPlaying: false,
    _cancelDetailWaveform: null,

    async init() {
      await Promise.all([
        this._loadSounds(true),
        this._loadLabels(),
        this._loadAnimals(),
      ]);
    },

    async _loadSounds(reset = false) {
      if (reset) {
        this.offset = 0;
        this.sounds = [];
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
        if (this.filterLabel)  params.label     = this.filterLabel;
        if (this.filterAnimal) params.animal_id = this.filterAnimal;

        const res = await getSounds(params);
        this.sounds = reset ? res.items : [...this.sounds, ...res.items];
        this.total = res.total;
        this.offset = this.sounds.length;
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

    async _loadAnimals() {
      const boot = window.__BOOTSTRAP__ || {};
      if (boot.animals) {
        this.animals = boot.animals;
        return;
      }
      try {
        const res = await getAnimals();
        this.animals = res.items;
      } catch {
        this.animals = [];
      }
    },

    animalName(animalId) {
      const animal = this.animals.find(a => a.id === animalId);
      return animal ? animal.name : '';
    },

    async changeSort(newSort) {
      this.sort = newSort;
      await this._loadSounds(true);
    },

    async recalculate() {
      try {
        const result = await recalculateUniqueness({ force: true });
        showToast(`Uniqueness updated (${result.updated_count} fingerprints computed)`, 'success');
        await this._loadSounds(true);
      } catch (err) {
        showToast(err.message || 'Recalculation failed', 'error');
      }
    },

    async toggleLabelFilter(label) {
      this.filterLabel = this.filterLabel === label ? '' : label;
      await this._loadSounds(true);
    },

    async setAnimalFilter(id) {
      this.filterAnimal = id;
      await this._loadSounds(true);
    },

    async loadMore() {
      if (this.isLoadingMore || this.sounds.length >= this.total) return;
      await this._loadSounds(false);
    },

    get hasMore() {
      return this.sounds.length < this.total;
    },

    /* ──────────────────────────────────────────────────────
       Inline playback
    ────────────────────────────────────────────────────── */

    async togglePlay(sound, event) {
      event.stopPropagation();

      if (this.playingId === sound.id) {
        audioPlayer.stop();
        this.playingId = null;
        return;
      }

      audioPlayer.stop();
      this.playingId = sound.id;

      // Record play (fire-and-forget)
      recordPlay(sound.id).catch(() => {});

      audioPlayer.onEnded = () => {
        if (this.playingId === sound.id) this.playingId = null;
      };
      audioPlayer.onError = () => {
        if (this.playingId === sound.id) this.playingId = null;
      };

      try {
        await audioPlayer.playWithFallback(sound.mp3_url, sound.wav_url);
      } catch {
        this.playingId = null;
      }
    },

    /* ──────────────────────────────────────────────────────
       Detail modal
    ────────────────────────────────────────────────────── */

    openDetail(sound) {
      audioPlayer.stop();
      this._stopDetailWaveform();
      this.playingId = null;
      this._detailIsPlaying = false;
      this.detailSound = { ...sound, labels: [...(sound.labels || [])] };
      this.detailTitle = sound.title || '';
      this.showDetail = true;
      this.showDeleteConfirm = false;
      this.labelInput = '';

      // Draw static waveform after modal is in the DOM
      this.$nextTick(() => {
        this._drawDetailWaveform(sound, 0);
      });
    },

    closeDetail() {
      audioPlayer.stop();
      this._stopDetailWaveform();
      this._detailIsPlaying = false;
      this.showDetail = false;
      this.detailSound = null;
      this.showDeleteConfirm = false;
    },

    _drawDetailWaveform(sound, progress) {
      const canvas = this.$refs.detailWaveformCanvas;
      if (!canvas || !sound?.waveform_data?.length) return;

      if (this._detailIsPlaying && progress === 0) {
        this._cancelDetailWaveform = animateWaveform(
          canvas,
          sound.waveform_data,
          getAccentColor(),
          () => {
            if (audioPlayer.duration === 0) return 0;
            return audioPlayer.currentTime / audioPlayer.duration;
          }
        );
      } else {
        drawWaveform(canvas, sound.waveform_data, getAccentColor(), progress);
      }
    },

    _stopDetailWaveform() {
      this._cancelDetailWaveform = cancelDraw(this._cancelDetailWaveform);
    },

    playDetailSound() {
      if (this._detailIsPlaying) {
        audioPlayer.stop();
        this._stopDetailWaveform();
        this._detailIsPlaying = false;
        return;
      }

      const sound = this.detailSound;
      if (!sound) return;

      this._detailIsPlaying = true;
      recordPlay(sound.id).catch(() => {});
      this._drawDetailWaveform(sound, 0);

      audioPlayer.onEnded = () => {
        this._detailIsPlaying = false;
        this._stopDetailWaveform();
        this._drawDetailWaveform(sound, 1);
      };
      audioPlayer.onError = () => {
        this._detailIsPlaying = false;
        this._stopDetailWaveform();
      };

      audioPlayer.playWithFallback(sound.mp3_url, sound.wav_url).catch(() => {
        this._detailIsPlaying = false;
        this._stopDetailWaveform();
      });
    },

    /* ──────────────────────────────────────────────────────
       Label editing
    ────────────────────────────────────────────────────── */

    removeLabel(label) {
      if (!this.detailSound) return;
      if (!this.requireAuth()) return;
      this.detailSound.labels = this.detailSound.labels.filter((l) => l !== label);
      this._saveLabels();
    },

    async addLabel() {
      const label = this.labelInput.trim().toLowerCase();
      if (!label || !this.detailSound) return;
      if (this.detailSound.labels.includes(label)) {
        this.labelInput = '';
        return;
      }
      if (!this.requireAuth()) return;
      this.detailSound.labels = [...this.detailSound.labels, label];
      this.labelInput = '';
      await this._saveLabels();
    },

    async _saveLabels() {
      if (!this.detailSound) return;
      if (!this.requireAuth()) return;
      try {
        await updateSound(this.detailSound.id, { labels: this.detailSound.labels });
        // Update the row in the list too
        const idx = this.sounds.findIndex((m) => m.id === this.detailSound.id);
        if (idx !== -1) {
          this.sounds[idx] = { ...this.sounds[idx], labels: [...this.detailSound.labels] };
        }
        // Refresh label filter chips
        await this._loadLabels();
      } catch (err) {
        showToast(err.message || 'Failed to save labels', 'error');
      }
    },

    async saveTitle() {
      if (!this.detailSound) return;
      if (!this.requireAuth()) return;
      try {
        const updated = await updateSound(this.detailSound.id, { title: this.detailTitle || null });
        this.detailSound = { ...updated, labels: updated.labels || [] };
        const idx = this.sounds.findIndex((m) => m.id === this.detailSound.id);
        if (idx !== -1) this.sounds[idx] = { ...this.sounds[idx], title: updated.title };
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

    async deleteSoundConfirmed() {
      if (!this.detailSound) return;
      if (!this.requireAuth()) return;
      const id = this.detailSound.id;
      try {
        await deleteSound(id);
        this.sounds = this.sounds.filter((m) => m.id !== id);
        this.total = Math.max(0, this.total - 1);
        this.closeDetail();
        showToast('Sound deleted', 'success');
        // Refresh label counts
        await this._loadLabels();
      } catch (err) {
        showToast(err.message || 'Failed to delete', 'error');
      }
    },

  };
}
