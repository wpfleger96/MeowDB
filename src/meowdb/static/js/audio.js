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
    this._settle = null;
  }

  /** @param {(event: Event) => void} cb */
  set onPlaying(cb) { this._onPlaying = cb; }

  /** @param {(event: Event) => void} cb */
  set onEnded(cb) { this._onEnded = cb; }

  /** @param {(event: Event) => void} cb */
  set onError(cb) { this._onError = cb; }

  /**
   * Play audio from a URL. Returns a Promise that resolves when playback
   * finishes (or is intentionally superseded by stop()) and rejects only on a
   * genuine media error.
   *
   * MUST be called from within a user gesture on iOS Safari.
   *
   * @param {string} url
   * @returns {Promise<void>}
   */
  play(url) {
    this.stop();
    return this._run(url, null);
  }

  /**
   * Play a primary URL, falling back to a secondary URL if the primary fails
   * to load/decode. Only a genuine error on the final source reaches onError;
   * an intentional stop()/supersede resolves cleanly.
   *
   * @param {string} url
   * @param {string|null} [fallbackUrl]
   * @returns {Promise<void>}
   */
  playWithFallback(url, fallbackUrl = null) {
    this.stop();
    return this._run(url, fallbackUrl);
  }

  /**
   * Core playback loop for a single <audio> element. Every callback is guarded
   * by element identity (this._audio === audio) so a superseded element —
   * stopped, or replaced by a newer play() — can never fire onEnded/onError or
   * settle the promise. A genuine error tries the fallback URL (if any) before
   * surfacing onError.
   *
   * @param {string} url
   * @param {string|null} fallbackUrl
   * @returns {Promise<void>}
   */
  _run(url, fallbackUrl) {
    return new Promise((resolve, reject) => {
      const audio = new Audio();
      this._audio = audio;
      this._currentUrl = url;
      this._settle = resolve; // stop() calls this to resolve an interrupted play cleanly
      audio.preload = 'auto';

      const fail = (err) => {
        if (this._audio !== audio) return; // superseded — ignore
        // Clear before recursing so the fallback _run owns the fresh element/settle.
        this._audio = null;
        this._settle = null;
        if (fallbackUrl) {
          this._run(fallbackUrl, null).then(resolve, reject);
          return;
        }
        if (this._onError) this._onError(err);
        reject(err);
      };

      audio.addEventListener('playing', (e) => {
        if (this._audio === audio && this._onPlaying) this._onPlaying(e);
      });

      audio.addEventListener('ended', (e) => {
        if (this._audio !== audio) return;
        this._audio = null;
        this._settle = null;
        if (this._onEnded) this._onEnded(e);
        resolve();
      });

      audio.addEventListener('error', () => {
        fail(new Error(`Audio error: ${audio.error?.message || 'unknown'}`));
      });

      audio.src = url;
      audio.play().catch((err) => {
        // AbortError is the expected interrupt from stop(); the identity guard
        // in fail() covers any later rejection after a supersede.
        if (err.name === 'AbortError') return;
        fail(err);
      });
    });
  }

  /**
   * Stop any current playback. Marks the element superseded (so its callbacks
   * become inert) and resolves the in-flight promise cleanly, so clearing src
   * can never surface a user-facing error.
   */
  stop() {
    if (this._audio) {
      const audio = this._audio;
      const settle = this._settle;
      this._audio = null;
      this._currentUrl = null;
      this._settle = null;
      audio.pause();
      audio.src = '';
      if (settle) settle();
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
