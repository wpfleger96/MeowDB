/* ============================================================
   audio.js — AudioPlayer class + MediaRecorder wrapper
   ============================================================ */

/**
 * AudioPlayer wraps an HTML5 <audio> element.
 *
 * iOS Safari caveat: audio.play() must be called from within a user
 * gesture handler. The caller is responsible for ensuring this — do not
 * call play() from setTimeout, fetch callbacks, or similar async paths
 * that are not chained from an original user event.
 */
class AudioPlayer {
  constructor() {
    this._audio = null;
    this._currentUrl = null;
    this._onPlaying = null;
    this._onEnded = null;
    this._onError = null;
  }

  /** @param {(event: Event) => void} cb */
  set onPlaying(cb) { this._onPlaying = cb; }

  /** @param {(event: Event) => void} cb */
  set onEnded(cb) { this._onEnded = cb; }

  /** @param {(event: Event) => void} cb */
  set onError(cb) { this._onError = cb; }

  /**
   * Play audio from a URL. Returns a Promise that resolves when the
   * audio finishes (or rejects on error/abort).
   *
   * MUST be called from within a user gesture on iOS Safari.
   *
   * @param {string} url
   * @returns {Promise<void>}
   */
  play(url) {
    this.stop();

    return new Promise((resolve, reject) => {
      const audio = new Audio();
      this._audio = audio;
      this._currentUrl = url;

      audio.preload = 'auto';

      audio.addEventListener('playing', (e) => {
        if (this._onPlaying) this._onPlaying(e);
      });

      audio.addEventListener('ended', (e) => {
        if (this._onEnded) this._onEnded(e);
        this._audio = null;
        resolve();
      });

      audio.addEventListener('error', (e) => {
        const err = new Error(`Audio error: ${audio.error?.message || 'unknown'}`);
        if (this._onError) this._onError(err);
        this._audio = null;
        reject(err);
      });

      audio.src = url;

      // play() returns a Promise on modern browsers; catch rejection
      // (e.g. AbortError when stop() is called before playback starts)
      audio.play().catch((err) => {
        // AbortError is expected when stop() interrupts; resolve cleanly
        if (err.name === 'AbortError') {
          resolve();
        } else {
          if (this._onError) this._onError(err);
          reject(err);
        }
      });
    });
  }

  /**
   * Play audio from a primary URL, falling back to a secondary URL on error.
   * Suppresses the onError callback during the primary attempt so a failed
   * primary does not surface an error before the fallback is tried.
   *
   * @param {string} url
   * @param {string|null} [fallbackUrl]
   * @returns {Promise<void>}
   */
  async playWithFallback(url, fallbackUrl = null) {
    if (!fallbackUrl) {
      return this.play(url);
    }
    const savedOnError = this._onError;
    this._onError = null;
    try {
      await this.play(url);
    } catch {
      this._onError = savedOnError;
      await this.play(fallbackUrl);
      return;
    }
    this._onError = savedOnError;
  }

  /**
   * Stop any current playback.
   */
  stop() {
    if (this._audio) {
      this._audio.pause();
      this._audio.src = '';
      this._audio = null;
      this._currentUrl = null;
    }
  }

  /** @returns {boolean} */
  get isPlaying() {
    return this._audio !== null && !this._audio.paused;
  }

  /** @returns {string|null} */
  get currentUrl() {
    return this._currentUrl;
  }

  /** @returns {number} */
  get currentTime() {
    return this._audio ? this._audio.currentTime : 0;
  }

  /** @returns {number} */
  get duration() {
    return this._audio ? this._audio.duration || 0 : 0;
  }
}

/* ============================================================
   MicRecorder — MediaRecorder wrapper for in-browser recording
   ============================================================ */

class MicRecorder {
  constructor() {
    this._stream = null;
    this._recorder = null;
    this._chunks = [];
    this._startTime = null;
    this._timerId = null;
    this._onTick = null;
    this._onStop = null;
  }

  /** @param {(seconds: number) => void} cb */
  set onTick(cb) { this._onTick = cb; }

  /**
   * Called when recording stops.
   * @param {(blob: Blob) => void} cb
   */
  set onStop(cb) { this._onStop = cb; }

  /** @returns {boolean} */
  get isRecording() {
    return this._recorder !== null && this._recorder.state === 'recording';
  }

  /**
   * Request mic access and start recording.
   * Must be called from a user gesture.
   * @returns {Promise<void>}
   */
  async start() {
    if (this.isRecording) return;

    this._stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    this._chunks = [];

    // Prefer WebM/opus; fall back to whatever the browser offers
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : '';

    this._recorder = new MediaRecorder(this._stream, mimeType ? { mimeType } : {});

    this._recorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) this._chunks.push(e.data);
    });

    this._recorder.addEventListener('stop', () => {
      const blob = new Blob(this._chunks, { type: this._recorder.mimeType || 'audio/webm' });
      this._chunks = [];
      this._cleanup();
      if (this._onStop) this._onStop(blob);
    });

    this._recorder.start(100); // collect chunks every 100ms
    this._startTime = Date.now();

    // Tick timer for UI clock
    this._timerId = setInterval(() => {
      const elapsed = Math.floor((Date.now() - this._startTime) / 1000);
      if (this._onTick) this._onTick(elapsed);
    }, 1000);
  }

  /**
   * Stop recording; triggers the onStop callback with the recorded Blob.
   */
  stop() {
    if (this._recorder && this._recorder.state === 'recording') {
      this._recorder.stop();
    }
    if (this._timerId) {
      clearInterval(this._timerId);
      this._timerId = null;
    }
  }

  _cleanup() {
    if (this._stream) {
      this._stream.getTracks().forEach((t) => t.stop());
      this._stream = null;
    }
    this._recorder = null;
    this._startTime = null;
  }
}

// Singletons used by view components
const audioPlayer = new AudioPlayer();
const micRecorder = new MicRecorder();
