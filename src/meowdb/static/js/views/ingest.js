/* ============================================================
   views/ingest.js — Upload + waveform clipping Alpine component
   ============================================================ */

function ingestView() {
  return {
    phase: 'idle',

    jobs: [],

    uploadProgress: { done: 0, total: 0, errors: [] },

    isDragOver: false,
    isRecording: false,
    recordSeconds: 0,
    _recordInterval: null,
    _resetting: false,

    _wavesurferLoaded: false,

    /* ──────────────────────────────────────────────────────
       Lifecycle
    ────────────────────────────────────────────────────── */

    init() {
      this._wavesurfers = new Map();
      try {
        micRecorder.onTick = (s) => { this.recordSeconds = s; };
        micRecorder.onStop = (blob) => { this._uploadBlob(blob); };
      } catch (e) {
        console.error('ingestView init error:', e);
      }
    },

    destroy() {
      for (const job of this.jobs) {
        this._destroyWaveSurferForJob(job);
      }
      this._wavesurfers = new Map();
    },

    /* ──────────────────────────────────────────────────────
       Upload
    ────────────────────────────────────────────────────── */

    onFileChange(event) {
      const files = Array.from(event.target.files || []);
      event.target.value = '';
      if (files.length > 0) this._uploadFiles(files);
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
      const files = Array.from(event.dataTransfer?.files || []).filter(
        f => f.type.startsWith('audio/') || f.type.startsWith('video/')
      );
      if (files.length > 0) this._uploadFiles(files);
    },

    async _uploadFiles(files) {
      if (this._resetting) return;
      if (this.authRequired && !this.authenticated) {
        this.showLoginModal = true;
        return;
      }

      this.phase = 'uploading';
      this.uploadProgress = { done: 0, total: files.length, errors: [] };
      for (const job of this.jobs) {
        this._destroyWaveSurferForJob(job);
      }
      this.jobs = [];

      await this._ensureWaveSurfer();

      for (let i = 0; i < files.length; i++) {
        if (this._resetting) return;
        const file = files[i];
        this.jobs.push({
          jobId: null,
          filename: file.name,
          phase: 'uploading',
          errorMessage: null,
          isAutoDetecting: false,
          regionCount: 0,
          clips: [],
          zoomLevel: 0,
          _minPxPerSec: 0,
          duration: 0,
          currentTime: 0,
          containerId: 'clip-waveform-' + i,
        });
        const job = this.jobs[i];

        try {
          const result = await createIngestJob(file);
          job.jobId = result.job_id;
          job.phase = 'clipping';
        } catch (err) {
          job.phase = 'error';
          job.errorMessage = err.message || 'Upload failed';
          this.uploadProgress.errors.push(file.name);
        }
        this.uploadProgress.done++;
      }

      const successJobs = this.jobs.filter(j => j.phase === 'clipping');
      if (successJobs.length === 0) {
        this.phase = 'idle';
        showToast('All uploads failed', 'error');
        return;
      }

      this.phase = 'clipping';

      if (this.uploadProgress.errors.length > 0) {
        showToast(
          `${this.uploadProgress.errors.length} of ${files.length} uploads failed`,
          'error'
        );
      }

      this.$nextTick(() => {
        requestAnimationFrame(() => {
          for (const job of successJobs) {
            if (!this._resetting) this._initWaveSurferForJob(job);
          }
        });
      });
    },

    async _uploadBlob(blob) {
      const file = new File([blob], 'recording.webm', { type: blob.type });
      await this._uploadFiles([file]);
    },

    /* ──────────────────────────────────────────────────────
       Recording
    ────────────────────────────────────────────────────── */

    async startRecording() {
      if (this.authRequired && !this.authenticated) { this.showLoginModal = true; return; }
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
      await this._loadScript('/static/vendor/wavesurfer-timeline.min.js');
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

    _initWaveSurferForJob(job) {
      const container = document.getElementById(job.containerId);
      if (!container) {
        console.warn('WaveSurfer container not found:', job.containerId);
        return;
      }

      const regionsPlugin = WaveSurfer.Regions.create();
      regionsPlugin.__v_skip = true;

      const ws = WaveSurfer.create({
        container,
        waveColor: 'var(--border-strong)',
        progressColor: 'var(--accent)',
        cursorColor: 'var(--accent)',
        barWidth: 2,
        barGap: 1,
        height: 120,
        normalize: true,
        interact: true,
        scrollParent: true,
        url: sourceAudioUrl(job.jobId),
        plugins: [
          regionsPlugin,
          WaveSurfer.Timeline.create({
            height: 20,
            style: { color: 'var(--text-secondary)', fontSize: '10px' },
          }),
        ],
      });
      ws.__v_skip = true;

      this._wavesurfers.set(job.containerId, { ws, regions: regionsPlugin });

      ws.on('ready', () => {
        const duration = ws.getDuration();
        job.duration = duration;
        job.currentTime = 0;
        if (duration > 0) {
          job._minPxPerSec = container.clientWidth / duration;
        }
      });

      ws.on('timeupdate', (t) => { job.currentTime = t; });

      regionsPlugin.enableDragSelection({ color: 'rgba(255, 107, 107, 0.25)' });

      regionsPlugin.on('region-created', (region) => {
        job.regionCount = regionsPlugin.getRegions().length;
        this._addDeleteButton(region);
        job.clips.push({ id: region.id, start: region.start, end: region.end, region });
      });
      regionsPlugin.on('region-removed', (region) => {
        job.regionCount = regionsPlugin.getRegions().length;
        job.clips = job.clips.filter(c => c.id !== region.id);
      });
      regionsPlugin.on('region-updated', (region) => {
        const clip = job.clips.find(c => c.id === region.id);
        if (clip) {
          clip.start = region.start;
          clip.end = region.end;
        }
      });
    },

    _addDeleteButton(region) {
      const btn = document.createElement('button');
      btn.className = 'region-delete-btn';
      btn.innerHTML = '&times;';
      btn.setAttribute('aria-label', 'Delete region');
      btn.style.pointerEvents = 'auto';
      btn.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        e.stopImmediatePropagation();
      });
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        region.remove();
      });
      region.element.appendChild(btn);
    },

    _destroyWaveSurferForJob(job) {
      const entry = this._wavesurfers?.get(job.containerId);
      if (entry) {
        try { entry.ws.destroy(); } catch {}
        this._wavesurfers.delete(job.containerId);
      }
      job.duration = 0;
      job.currentTime = 0;
    },

    /* ──────────────────────────────────────────────────────
       Per-job actions
    ────────────────────────────────────────────────────── */

    zoomIn(job) {
      if (job.zoomLevel >= 10) return;
      job.zoomLevel += 1;
      this._applyZoom(job);
    },

    zoomOut(job) {
      if (job.zoomLevel <= 0) return;
      job.zoomLevel -= 1;
      this._applyZoom(job);
    },

    _applyZoom(job) {
      const entry = this._wavesurfers?.get(job.containerId);
      if (!entry || job._minPxPerSec === 0) return;
      const pxPerSec = job._minPxPerSec * Math.pow(2, job.zoomLevel);
      entry.ws.zoom(pxPerSec);
    },

    togglePlayPause(job) {
      const entry = this._wavesurfers?.get(job.containerId);
      if (entry) entry.ws.playPause();
    },

    async autoDetect(job) {
      if (this.authRequired && !this.authenticated) {
        this.showLoginModal = true;
        return;
      }
      job.isAutoDetecting = true;
      try {
        const result = await detectRegions(job.jobId);
        job.clips = [];
        const entry = this._wavesurfers?.get(job.containerId);
        if (entry) {
          entry.regions.clearRegions();
          for (const r of result.regions) {
            entry.regions.addRegion({
              start: r.start_ms / 1000,
              end: r.end_ms / 1000,
              color: 'rgba(255, 107, 107, 0.25)',
              drag: true,
              resize: true,
            });
          }
          job.regionCount = entry.regions.getRegions().length;
        }
        if (result.regions.length === 0) {
          showToast('No meows detected — draw regions manually', 'info');
        }
      } catch (err) {
        showToast(err.message || 'Auto-detect failed', 'error');
      } finally {
        job.isAutoDetecting = false;
      }
    },

    playClip(job, clip) {
      const entry = this._wavesurfers?.get(job.containerId);
      if (entry) entry.ws.play(clip.start, clip.end);
    },

    removeClip(job, clip) {
      if (clip.region) clip.region.remove();
    },

    async saveClips(job) {
      if (this.authRequired && !this.authenticated) {
        this.showLoginModal = true;
        return;
      }
      const entry = this._wavesurfers?.get(job.containerId);
      if (!entry) return;
      const regions = entry.regions.getRegions();
      if (regions.length === 0) {
        showToast('Draw at least one region first', 'info');
        return;
      }
      const regionData = regions.map(r => ({
        start_ms: Math.round(r.start * 1000),
        end_ms: Math.round(r.end * 1000),
      }));
      regionData.sort((a, b) => a.start_ms - b.start_ms);

      job.phase = 'processing';

      try {
        const result = await clipAndCommit(job.jobId, regionData);
        this._destroyWaveSurferForJob(job);
        job.phase = 'done';
        showToast('Saved ' + result.meow_ids.length + ' meow' + (result.meow_ids.length !== 1 ? 's' : ''), 'success');
        if (this.jobs.every(j => j.phase === 'done' || j.phase === 'error')) {
          this.phase = 'done';
        }
      } catch (err) {
        job.phase = 'clipping';
        showToast(err.message || 'Save failed', 'error');
      }
    },

    async saveAllClips() {
      if (this.authRequired && !this.authenticated) {
        this.showLoginModal = true;
        return;
      }
      const clippingJobs = this.jobs.filter(j => j.phase === 'clipping');
      for (const job of clippingJobs) {
        const entry = this._wavesurfers?.get(job.containerId);
        if (entry && entry.regions.getRegions().length > 0) {
          await this.saveClips(job);
        }
      }
    },

    reset() {
      this._resetting = true;
      if (this.isRecording) this.stopRecording();
      for (const job of this.jobs) {
        this._destroyWaveSurferForJob(job);
      }
      audioPlayer.stop();
      this.jobs = [];
      this.phase = 'idle';
      this.uploadProgress = { done: 0, total: 0, errors: [] };
      this._resetting = false;
    },

    /* ──────────────────────────────────────────────────────
       Formatting helpers
    ────────────────────────────────────────────────────── */

    formatDuration(ms) { return MeowUtils.formatDuration(ms); },

    formatTimecode(s) {
      const m = Math.floor(s / 60);
      const sec = Math.floor(s % 60).toString().padStart(2, '0');
      return `${m}:${sec}`;
    },
  };
}
