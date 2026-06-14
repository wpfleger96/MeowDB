/* ============================================================
   views/ingest.js — Upload + review card-swipe Alpine component
   ============================================================ */

function ingestView() {
  return {
    // Phase: 'idle' | 'uploading' | 'processing' | 'review' | 'summary' | 'done'
    phase: 'idle',
    jobId: null,
    segments: [],
    currentIndex: 0,
    decisions: {},   // segmentId → 'accept' | 'reject'
    statusMessage: '',
    _pollTimer: null,
    isDragOver: false,

    // Recording state
    isRecording: false,
    recordSeconds: 0,

    // Swipe state
    _touchStartX: 0,
    _touchStartY: 0,
    _dragX: 0,
    _isSwiping: false,

    /* ──────────────────────────────────────────────────────
       Lifecycle
    ────────────────────────────────────────────────────── */

    init() {
      micRecorder.onTick = (s) => { this.recordSeconds = s; };
      micRecorder.onStop = (blob) => { this._uploadBlob(blob); };
    },

    destroy() {
      this._stopPoll();
    },

    /* ──────────────────────────────────────────────────────
       Upload
    ────────────────────────────────────────────────────── */

    onFileChange(event) {
      const file = event.target.files?.[0];
      if (file) this._uploadFile(file);
      // Reset input so same file can be re-selected
      event.target.value = '';
    },

    onDragOver(event) {
      event.preventDefault();
      this.isDragOver = true;
    },

    onDragLeave() {
      this.isDragOver = false;
    },

    onDrop(event) {
      event.preventDefault();
      this.isDragOver = false;
      const file = event.dataTransfer?.files?.[0];
      if (file) this._uploadFile(file);
    },

    async _uploadFile(file) {
      this.phase = 'uploading';
      this.statusMessage = 'Uploading…';
      try {
        const job = await createIngestJob(file);
        this.jobId = job.job_id;
        this.phase = 'processing';
        this.statusMessage = 'Extracting meows…';
        this._startPoll();
      } catch (err) {
        this.phase = 'idle';
        showToast(err.message || 'Upload failed', 'error');
      }
    },

    /* ──────────────────────────────────────────────────────
       Recording
    ────────────────────────────────────────────────────── */

    async startRecording() {
      try {
        this.isRecording = true;
        this.recordSeconds = 0;
        await micRecorder.start();
      } catch (err) {
        this.isRecording = false;
        showToast('Microphone access denied', 'error');
      }
    },

    stopRecording() {
      if (this.isRecording) {
        micRecorder.stop();
        this.isRecording = false;
      }
    },

    async _uploadBlob(blob) {
      const file = new File([blob], 'recording.webm', { type: blob.type });
      await this._uploadFile(file);
    },

    formatRecordTime(seconds) {
      const m = Math.floor(seconds / 60).toString().padStart(2, '0');
      const s = (seconds % 60).toString().padStart(2, '0');
      return `${m}:${s}`;
    },

    /* ──────────────────────────────────────────────────────
       Polling
    ────────────────────────────────────────────────────── */

    _startPoll() {
      this._pollTimer = setInterval(async () => {
        try {
          const job = await getIngestJob(this.jobId);
          if (job.status === 'ready') {
            this._stopPoll();
            if (!job.segments || job.segments.length === 0) {
              this.phase = 'idle';
              showToast('No meows found in this recording', 'info');
              return;
            }
            this.segments = job.segments;
            this.currentIndex = 0;
            this.decisions = {};
            this.phase = 'review';
            this._nextTick_drawCard();
          } else if (job.status === 'failed') {
            this._stopPoll();
            this.phase = 'idle';
            showToast('Processing failed — try another file', 'error');
          }
        } catch (err) {
          this._stopPoll();
          this.phase = 'idle';
          showToast(err.message || 'Status check failed', 'error');
        }
      }, 600);
    },

    _stopPoll() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    },

    /* ──────────────────────────────────────────────────────
       Review: current card helpers
    ────────────────────────────────────────────────────── */

    get currentSegment() {
      return this.segments[this.currentIndex] || null;
    },

    get reviewProgress() {
      if (!this.segments.length) return 0;
      return this.currentIndex / this.segments.length;
    },

    get reviewLabel() {
      return `${this.currentIndex + 1} of ${this.segments.length}`;
    },

    get acceptedCount() {
      return Object.values(this.decisions).filter((d) => d === 'accept').length;
    },

    get rejectedCount() {
      return Object.values(this.decisions).filter((d) => d === 'reject').length;
    },

    _nextTick_drawCard() {
      this.$nextTick(() => {
        const seg = this.currentSegment;
        if (!seg) return;
        const canvas = document.getElementById('review-waveform');
        if (canvas && seg.waveform) {
          drawWaveform(canvas, seg.waveform, '#ff6b6b', 1);
        }
      });
    },

    async playCurrentSegment() {
      const seg = this.currentSegment;
      if (!seg) return;
      audioPlayer.stop();
      try {
        await audioPlayer.play(segmentAudioUrl(this.jobId, seg.id));
      } catch (err) {
        showToast('Playback error', 'error');
      }
    },

    /* ──────────────────────────────────────────────────────
       Accept / Reject
    ────────────────────────────────────────────────────── */

    acceptCurrent() {
      this._decide('accept');
    },

    rejectCurrent() {
      this._decide('reject');
    },

    _decide(decision) {
      const seg = this.currentSegment;
      if (!seg) return;
      audioPlayer.stop();
      this.decisions[seg.id] = decision;
      this._animateCard(decision, () => this._advance());
    },

    _advance() {
      const next = this.currentIndex + 1;
      if (next >= this.segments.length) {
        this.phase = 'summary';
      } else {
        this.currentIndex = next;
        this._resetCardTransform();
        this._nextTick_drawCard();
      }
    },

    _animateCard(decision, callback) {
      const card = document.getElementById('review-card');
      if (!card) { callback(); return; }

      const cls = decision === 'accept' ? 'accept-anim' : 'reject-anim';
      card.classList.add(cls);
      card.addEventListener('animationend', () => {
        card.classList.remove(cls);
        callback();
      }, { once: true });
    },

    _resetCardTransform() {
      const card = document.getElementById('review-card');
      if (card) card.style.transform = '';
    },

    /* ──────────────────────────────────────────────────────
       Swipe gestures
    ────────────────────────────────────────────────────── */

    onTouchStart(e) {
      if (e.touches.length !== 1) return;
      this._touchStartX = e.touches[0].clientX;
      this._touchStartY = e.touches[0].clientY;
      this._dragX = 0;
      this._isSwiping = false;
      const card = document.getElementById('review-card');
      if (card) card.classList.add('swiping');
    },

    onTouchMove(e) {
      if (e.touches.length !== 1) return;
      const dx = e.touches[0].clientX - this._touchStartX;
      const dy = e.touches[0].clientY - this._touchStartY;

      // Ignore if scrolling vertically
      if (!this._isSwiping && Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 8) return;
      this._isSwiping = true;
      e.preventDefault();

      this._dragX = dx;
      const rotate = dx * 0.06;
      const card = document.getElementById('review-card');
      if (card) card.style.transform = `translateX(${dx}px) rotate(${rotate}deg)`;

      // Show hint overlays
      const threshold = 40;
      const acceptHint = document.getElementById('hint-accept');
      const rejectHint = document.getElementById('hint-reject');
      if (acceptHint) acceptHint.style.opacity = dx >  threshold ? Math.min(1, (dx - threshold) / 40).toString() : '0';
      if (rejectHint) rejectHint.style.opacity = dx < -threshold ? Math.min(1, (-dx - threshold) / 40).toString() : '0';
    },

    onTouchEnd() {
      const card = document.getElementById('review-card');
      if (card) card.classList.remove('swiping');

      // Reset hint overlays
      const acceptHint = document.getElementById('hint-accept');
      const rejectHint = document.getElementById('hint-reject');
      if (acceptHint) acceptHint.style.opacity = '0';
      if (rejectHint) rejectHint.style.opacity = '0';

      const THRESHOLD = 80;
      if (this._dragX >  THRESHOLD) {
        this._decide('accept');
      } else if (this._dragX < -THRESHOLD) {
        this._decide('reject');
      } else {
        // Spring back
        this._resetCardTransform();
      }

      this._dragX = 0;
      this._isSwiping = false;
    },

    /* ──────────────────────────────────────────────────────
       Commit
    ────────────────────────────────────────────────────── */

    async commitJob() {
      const accepted = Object.entries(this.decisions)
        .filter(([, v]) => v === 'accept')
        .map(([k]) => k);
      const rejected = Object.entries(this.decisions)
        .filter(([, v]) => v === 'reject')
        .map(([k]) => k);

      this.phase = 'uploading';
      this.statusMessage = `Saving ${accepted.length} meow${accepted.length !== 1 ? 's' : ''}…`;

      try {
        const result = await commitJob(this.jobId, accepted, rejected);
        this.phase = 'done';
        showToast(`Saved ${result.meow_ids.length} meow${result.meow_ids.length !== 1 ? 's' : ''} 🐱`, 'success');
      } catch (err) {
        this.phase = 'summary';
        showToast(err.message || 'Commit failed', 'error');
      }
    },

    reset() {
      this._stopPoll();
      audioPlayer.stop();
      this.phase = 'idle';
      this.jobId = null;
      this.segments = [];
      this.currentIndex = 0;
      this.decisions = {};
      this.statusMessage = '';
    },

    /* ──────────────────────────────────────────────────────
       Formatting helpers
    ────────────────────────────────────────────────────── */

    formatDuration(ms) { return MeowUtils.formatDuration(ms); },
  };
}
