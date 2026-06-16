/* ============================================================
   views/play.js — MEOW button Alpine component
   ============================================================ */

function playView() {
  return {
    meowCount: 0,
    isPlaying: false,
    isLoading: false,
    currentMeow: null,
    currentPhoto: null,
    _cancelWaveform: null,

    async init() {
      await this._refreshCount();
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
     * Main MEOW button handler.
     * Called directly from a click event — satisfies iOS user-gesture requirement.
     */
    async onMeowPress() {
      if (this.isLoading) return;

      // Stop any current playback immediately (within the gesture)
      if (this.isPlaying) {
        audioPlayer.stop();
        this._stopWaveform();
        this.isPlaying = false;
        return;
      }

      this.isLoading = true;

      let meow;
      try {
        meow = await getRandomMeow(this.currentMeow?.id);
      } catch (err) {
        this.isLoading = false;
        showToast(err.message || 'Could not fetch a meow', 'error');
        return;
      }

      this.currentMeow = meow;
      getRandomPhoto(this.currentPhoto?.id).then(photo => { this.currentPhoto = photo; }).catch(() => {});
      this.isLoading = false;
      this.isPlaying = true;

      // Record play event (fire-and-forget)
      recordPlay(meow.id).catch(() => {});

      // Draw initial waveform
      this._drawWaveform(meow, 0);

      // Set up callbacks before calling play()
      audioPlayer.onEnded = () => {
        this.isPlaying = false;
        this._stopWaveform();
        this._drawWaveform(meow, 1);
        this._refreshCount();
      };

      audioPlayer.onError = (err) => {
        this.isPlaying = false;
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

    /** Navigate to the upload view */
    goToUpload() {
      navigateTo('/upload');
    },
  };
}
