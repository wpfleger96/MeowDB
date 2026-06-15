/* ============================================================
   views/ingest.js — Upload + waveform clipping Alpine component
   ============================================================ */

function ingestView() {
  return {
    // Phase: 'idle' | 'uploading' | 'clipping' | 'processing' | 'done'
    phase: 'idle',
    jobId: null,
    statusMessage: '',
    isDragOver: false,

    // Recording state
    isRecording: false,
    recordSeconds: 0,
    _recordInterval: null,

    // Reset-in-progress guard (prevents in-flight uploads from writing phase/jobId)
    _resetting: false,

    // WaveSurfer state
    _wavesurfer: null,
    _regionsPlugin: null,
    _wavesurferLoaded: false,
    isAutoDetecting: false,
    regionCount: 0,

    /* ──────────────────────────────────────────────────────
       Lifecycle
    ────────────────────────────────────────────────────── */

    init() {
      try {
        micRecorder.onTick = (s) => { this.recordSeconds = s; };
        micRecorder.onStop = (blob) => { this._uploadBlob(blob); };
      } catch (e) {
        console.error('ingestView init error:', e);
      }
    },

    destroy() {
      this._destroyWaveSurfer();
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
      if (this._resetting) return;
      this.phase = 'uploading';
      this.statusMessage = 'Uploading…';
      try {
        const job = await createIngestJob(file);
        this.jobId = job.job_id;
        this.phase = 'clipping';
        await this._ensureWaveSurfer();
        this.$nextTick(() => this._initWaveSurfer());
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
       WaveSurfer
    ────────────────────────────────────────────────────── */

    async _ensureWaveSurfer() {
      if (this._wavesurferLoaded) return;
      await this._loadScript('/static/vendor/wavesurfer.min.js');
      await this._loadScript('/static/vendor/wavesurfer-regions.min.js');
      this._wavesurferLoaded = true;
    },

    _loadScript(src) {
      if (document.querySelector(`script[src="${src}"]`)) return Promise.resolve();
      return new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    },

    _initWaveSurfer() {
      const container = document.getElementById('clip-waveform-container');
      if (!container) return;

      this._regionsPlugin = WaveSurfer.Regions.create();
      this._wavesurfer = WaveSurfer.create({
        container,
        waveColor: 'var(--border-strong)',
        progressColor: 'var(--accent)',
        cursorColor: 'var(--accent)',
        barWidth: 2,
        barGap: 1,
        height: 120,
        normalize: true,
        interact: true,
        url: sourceAudioUrl(this.jobId),
        plugins: [this._regionsPlugin],
      });

      this._regionsPlugin.enableDragSelection({ color: 'rgba(255, 107, 107, 0.25)' });

      this._regionsPlugin.on('region-created', () => {
        this.regionCount = this._regionsPlugin.getRegions().length;
      });
      this._regionsPlugin.on('region-removed', () => {
        this.regionCount = this._regionsPlugin.getRegions().length;
      });
    },

    _destroyWaveSurfer() {
      if (this._wavesurfer) {
        try { this._wavesurfer.destroy(); } catch {}
        this._wavesurfer = null;
        this._regionsPlugin = null;
      }
    },

    togglePlayPause() {
      if (this._wavesurfer) this._wavesurfer.playPause();
    },

    async autoDetect() {
      this.isAutoDetecting = true;
      try {
        const result = await detectRegions(this.jobId);
        this._regionsPlugin.clearRegions();
        for (const r of result.regions) {
          this._regionsPlugin.addRegion({
            start: r.start_ms / 1000,
            end: r.end_ms / 1000,
            color: 'rgba(255, 107, 107, 0.25)',
            drag: true,
            resize: true,
          });
        }
        this.regionCount = this._regionsPlugin.getRegions().length;
        if (this.regionCount === 0) {
          showToast('No meows detected — draw regions manually', 'info');
        }
      } catch (err) {
        showToast(err.message || 'Auto-detect failed', 'error');
      } finally {
        this.isAutoDetecting = false;
      }
    },

    async saveClips() {
      const regions = this._regionsPlugin.getRegions();
      if (regions.length === 0) {
        showToast('Draw at least one region first', 'info');
        return;
      }
      const regionData = regions.map((r) => ({
        start_ms: Math.round(r.start * 1000),
        end_ms: Math.round(r.end * 1000),
      }));
      regionData.sort((a, b) => a.start_ms - b.start_ms);

      this.phase = 'processing';
      this.statusMessage = 'Processing ' + regions.length + ' clip' + (regions.length !== 1 ? 's' : '') + '…';

      try {
        const result = await clipAndCommit(this.jobId, regionData);
        this._destroyWaveSurfer();
        this.phase = 'done';
        showToast('Saved ' + result.meow_ids.length + ' meow' + (result.meow_ids.length !== 1 ? 's' : ''), 'success');
      } catch (err) {
        this.phase = 'clipping';
        showToast(err.message || 'Save failed', 'error');
      }
    },

    reset() {
      this._resetting = true;
      if (this.isRecording) this.stopRecording();
      this._destroyWaveSurfer();
      this.regionCount = 0;
      audioPlayer.stop();
      this.phase = 'idle';
      this.jobId = null;
      this.statusMessage = '';
      this._resetting = false;
    },

    /* ──────────────────────────────────────────────────────
       Formatting helpers
    ────────────────────────────────────────────────────── */

    formatDuration(ms) { return MeowUtils.formatDuration(ms); },
  };
}

