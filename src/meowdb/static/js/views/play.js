/* ============================================================
   views/play.js — MEOW button Alpine component
   ============================================================ */

function playView() {
  return {
    meowCount: null,
    isPlaying: false,
    isLoading: false,
    currentMeow: null,
    currentPhoto: null,
    feedbackGiven: null,
    _cancelWaveform: null,
    _gen: 0,

    async init() {
      this.isLoading = true;
      await this._refreshCount();
      this.isLoading = false;
      getRandomPhoto().then(photo => { this.currentPhoto = photo; }).catch(() => {});
    },

    async _refreshCount() {
      try {
        const res = await getMeows({ limit: 1 });
        this.meowCount = res.total;
      } catch {
        this.meowCount = 0;
      }
    },

    /**
     * Main MEOW button handler. Every tap cancels the current meow and advances
     * to a new random meow + photo. A generation counter ensures only the latest
     * tap's async work takes effect, so rapid taps land on the last one.
     * Called directly from a click event — satisfies iOS user-gesture requirement.
     */
    async onMeowPress() {
      const gen = ++this._gen;

      // Cancel the current meow within the gesture; stop() never errors.
      audioPlayer.stop();
      this._stopWaveform();
      this.isPlaying = false;
      this.isLoading = true;

      let meow;
      try {
        meow = await getRandomMeow(this.currentMeow?.id);
      } catch (err) {
        if (gen !== this._gen) return; // superseded by a newer tap
        this.isLoading = false;
        showToast(err.message || 'Could not fetch a meow', 'error');
        return;
      }
      if (gen !== this._gen) return; // a newer tap won; abandon this one

      this.currentMeow = meow;
      this.feedbackGiven = null;
      // New photo on every advance; guard so only the latest tap's photo sticks.
      getRandomPhoto(this.currentPhoto?.id)
        .then(photo => { if (gen === this._gen) this.currentPhoto = photo; })
        .catch(() => {});
      this.isLoading = false;
      this.isPlaying = true;

      // Record play event (fire-and-forget)
      recordPlay(meow.id).catch(() => {});

      // Draw initial waveform
      this._drawWaveform(meow, 0);

      // Set up callbacks before calling play(). No _gen guard needed here: the
      // audio core fires these only for the current element, and the next tap's
      // stop() reassigns them before a stale one could fire.
      audioPlayer.onEnded = () => {
        this.isPlaying = false;
        this._stopWaveform();
        this._drawWaveform(meow, 1);
        this._refreshCount();
      };

      audioPlayer.onError = (err) => {
        this.isPlaying = false;
        this.currentMeow = null;
        this.feedbackGiven = null;
        this._stopWaveform();
        showToast('Playback error: ' + (err.message || 'unknown'), 'error');
      };

      try {
        // play() must be called synchronously after user gesture
        await audioPlayer.playWithFallback(meow.mp3_url, meow.wav_url);
      } catch {
        this.isPlaying = false;
        this._stopWaveform();
      }
    },

    _drawWaveform(meow, progress) {
      const canvas = this.$refs.waveformCanvas;
      if (!canvas || !meow?.waveform_data?.length) return;

      if (this.isPlaying && progress === 0) {
        // Start animated waveform that tracks playback
        this._cancelWaveform = animateWaveform(
          canvas,
          meow.waveform_data,
          getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#ff6b6b',
          () => {
            if (audioPlayer.duration === 0) return 0;
            return audioPlayer.currentTime / audioPlayer.duration;
          }
        );
      } else {
        drawWaveform(
          canvas,
          meow.waveform_data,
          getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#ff6b6b',
          progress
        );
      }
    },

    _stopWaveform() {
      if (this._cancelWaveform) {
        this._cancelWaveform();
        this._cancelWaveform = null;
      }
    },

    uniquenessBadgeClass(score) {
      if (score == null) return 'badge-default';
      if (score >= 75) return 'badge-green';
      if (score >= 50) return 'badge-yellow';
      return 'badge-red';
    },

    submitFeedback(vote) {
      if (!this.currentMeow || this.feedbackGiven === vote) return;
      const previous = this.feedbackGiven;
      this.feedbackGiven = vote;
      const body = previous ? { vote, previous } : { vote };
      recordFeedback(this.currentMeow.id, body)
        .then(() => {
          showToast(vote === 'up' ? 'Upvoted!' : 'Downvoted', vote === 'up' ? 'success' : 'info');
        })
        .catch(() => {
          this.feedbackGiven = previous;
          showToast('Vote failed', 'error');
        });
    },

    /** Navigate to the upload view */
    goToUpload() {
      navigateTo('/upload');
    },
  };
}
