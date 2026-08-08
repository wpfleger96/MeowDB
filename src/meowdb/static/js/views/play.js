/* ============================================================
   views/play.js — MEOW button Alpine component
   ============================================================ */

function playView() {
  return {
    soundCount: null,
    isPlaying: false,
    // Must start true: Alpine evaluates the x-if wrapping the MEOW button
    // against these initializers before init() runs, and a false start
    // collapses the play area for one frame (layout shift).
    isLoading: true,
    currentSound: null,
    currentPhoto: null,
    feedbackGiven: null,
    _cancelWaveform: null,
    _gen: 0,

    async init() {
      const boot = window.__BOOTSTRAP__ || {};
      if (boot.photo) this.currentPhoto = boot.photo;
      else getRandomPhoto().then(photo => { this.currentPhoto = photo; }).catch(() => {});
      if (typeof boot.sound_count === 'number') this.soundCount = boot.sound_count;
      else await this._refreshCount();
      this.isLoading = false;
    },

    async _refreshCount() {
      try {
        const res = await getSounds({ limit: 1 });
        this.soundCount = res.total;
      } catch {
        this.soundCount = 0;
      }
    },

    /**
     * Main MEOW button handler. Every tap cancels the current sound and advances
     * to a new random sound + photo. A generation counter ensures only the latest
     * tap's async work takes effect, so rapid taps land on the last one.
     * Called directly from a click event — satisfies iOS user-gesture requirement.
     */
    async onMeowPress() {
      const gen = ++this._gen;

      // Cancel the current sound within the gesture; stop() never errors.
      audioPlayer.stop();
      this._stopWaveform();
      this.isPlaying = false;
      this.isLoading = true;

      let sound;
      try {
        sound = await getRandomSound(this.currentSound?.id, this.currentPhoto?.id);
      } catch (err) {
        if (gen !== this._gen) return; // superseded by a newer tap
        this.isLoading = false;
        showToast(err.message || 'Could not fetch a sound', 'error');
        return;
      }
      if (gen !== this._gen) return; // a newer tap won; abandon this one

      this.currentSound = sound;
      this.feedbackGiven = null;
      // Photo comes embedded in the sound response; may be null (no photos for this animal).
      // Never substitute another animal's photo — null renders the photo-less button state.
      this.currentPhoto = sound.photo;
      this.isLoading = false;

      await this._playCurrent(sound);
    },

    /**
     * Replay the sound that's already loaded, without advancing to a new one.
     * Shares the gesture/cancel contract with onMeowPress: bumping _gen and
     * calling audioPlayer.stop() here means an in-flight advance is abandoned,
     * and a later advance abandons this replay. Called directly from the click
     * handler so it satisfies the iOS user-gesture requirement.
     */
    async replaySound() {
      if (!this.currentSound || this.isLoading) return;

      ++this._gen;
      audioPlayer.stop();
      this._stopWaveform();
      this.isPlaying = false;

      // A replay is a fresh listen, so allow re-voting on the same sound.
      this.feedbackGiven = null;

      await this._playCurrent(this.currentSound);
    },

    /**
     * Play the given sound from the start: record the play, draw + animate the
     * waveform, wire the audio callbacks, and start playback. Shared tail of
     * onMeowPress() and replaySound(); the caller has already settled currentSound
     * and the generation counter.
     */
    async _playCurrent(sound) {
      this.isPlaying = true;

      // Record play event (fire-and-forget)
      recordPlay(sound.id).catch(() => {});

      // Draw initial waveform
      this._drawWaveform(sound, 0);

      // Set up callbacks before calling play(). No _gen guard needed here: the
      // audio core fires these only for the current element, and the next tap's
      // stop() reassigns them before a stale one could fire.
      audioPlayer.onEnded = () => {
        this.isPlaying = false;
        this._stopWaveform();
        this._drawWaveform(sound, 1);
        this._refreshCount();
      };

      audioPlayer.onError = (err) => {
        this.isPlaying = false;
        this.currentSound = null;
        this.feedbackGiven = null;
        this._stopWaveform();
        showToast('Playback error: ' + (err.message || 'unknown'), 'error');
      };

      try {
        // play() must be called synchronously after user gesture
        await audioPlayer.playWithFallback(sound.mp3_url, sound.wav_url);
      } catch {
        this.isPlaying = false;
        this._stopWaveform();
      }
    },

    _drawWaveform(sound, progress) {
      const canvas = this.$refs.waveformCanvas;
      if (!canvas || !sound?.waveform_data?.length) return;

      if (this.isPlaying && progress === 0) {
        // Start animated waveform that tracks playback
        this._cancelWaveform = animateWaveform(
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

    _stopWaveform() {
      this._cancelWaveform = cancelDraw(this._cancelWaveform);
    },

    submitFeedback(vote) {
      if (!this.currentSound || this.feedbackGiven === vote) return;
      const previous = this.feedbackGiven;
      this.feedbackGiven = vote;
      const body = previous ? { vote, previous } : { vote };
      recordFeedback(this.currentSound.id, body)
        .then(() => {
          showToast(vote === 'up' ? 'Upvoted!' : 'Downvoted', vote === 'up' ? 'success' : 'info');
        })
        .catch(() => {
          this.feedbackGiven = previous;
          showToast('Vote failed', 'error');
        });
    },

  };
}
