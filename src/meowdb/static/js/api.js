/* ============================================================
   api.js — fetch() wrappers for all API endpoints
   All functions return parsed JSON or throw on non-2xx.
   ============================================================ */

const API_BASE = '/api';

/**
 * Core fetch wrapper. Throws on non-2xx with the response body as message.
 * @param {string} path
 * @param {RequestInit} [opts]
 * @returns {Promise<any>}
 */
async function apiFetch(path, opts = {}) {
  const res = await fetch(API_BASE + path, {
    headers: { 'Accept': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });

  if (res.status === 204 || res.headers.get('content-length') === '0') {
    if (!res.ok) {
      throw new Error(`API error ${res.status}: ${path}`);
    }
    return null;
  }

  const body = await res.json().catch(() => ({ detail: res.statusText }));

  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new CustomEvent('auth-expired'));
  }

  if (!res.ok) {
    const msg = body?.detail || `API error ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }

  return body;
}

/* ============================================================
   Meows
   ============================================================ */

/**
 * @param {{ sort?: string, label?: string, limit?: number, offset?: number }} [params]
 * @returns {Promise<{ items: object[], total: number, limit: number, offset: number }>}
 */
async function getMeows(params = {}) {
  const qs = new URLSearchParams();
  if (params.sort)   qs.set('sort', params.sort);
  if (params.label)  qs.set('label', params.label);
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return apiFetch('/meows' + (q ? '?' + q : ''));
}

/**
 * @returns {Promise<object>} RandomMeowResponse with mp3_url, waveform_data, etc.
 */
async function getRandomMeow(excludeId) {
  return apiFetch('/meows/random' + (excludeId ? '?exclude=' + encodeURIComponent(excludeId) : ''));
}

/**
 * @param {string} id
 * @param {string[]} labels
 * @returns {Promise<object>}
 */
async function updateLabels(id, labels) {
  return apiFetch(`/meows/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ labels }),
  });
}

/**
 * @param {string} id
 * @param {{ labels?: string[], title?: string|null, recorded_at?: string|null }} fields
 * @returns {Promise<object>}
 */
async function updateMeow(id, fields) {
  return apiFetch(`/meows/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
}

/**
 * @param {string} id
 * @returns {Promise<null>}
 */
async function deleteMeow(id) {
  return apiFetch(`/meows/${id}`, { method: 'DELETE' });
}

/**
 * Record a play event (fire-and-forget — do not await in hot path).
 * @param {string} id
 * @returns {Promise<null>}
 */
async function recordPlay(id) {
  return apiFetch(`/meows/${id}/play`, { method: 'POST' });
}

/* ============================================================
   Ingest / Upload
   ============================================================ */

/**
 * Upload an audio file and create an ingest job.
 * @param {File|Blob} file
 * @returns {Promise<{ job_id: string, status: string }>}
 */
async function createIngestJob(file) {
  const form = new FormData();
  form.append('file', file, file.name || 'recording.webm');
  return apiFetch('/ingest', { method: 'POST', body: form });
}

/**
 * Poll job status.
 * @param {string} jobId
 * @returns {Promise<{ job_id: string, status: string, segments?: object[] }>}
 */
async function getIngestJob(jobId) {
  return apiFetch(`/ingest/${jobId}`);
}

/**
 * Commit a job: save accepted segments, discard rejected.
 * @param {string} jobId
 * @param {string[]} acceptedIds
 * @param {string[]} rejectedIds
 * @returns {Promise<{ meow_ids: string[], rejected_count: number }>}
 */
async function commitJob(jobId, acceptedIds, rejectedIds) {
  return apiFetch(`/ingest/${jobId}/commit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accepted_ids: acceptedIds, rejected_ids: rejectedIds }),
  });
}

/**
 * Delete a job and all staging files.
 * @param {string} jobId
 * @returns {Promise<null>}
 */
async function deleteJob(jobId) {
  return apiFetch(`/ingest/${jobId}`, { method: 'DELETE' });
}

/**
 * Build the streaming URL for a staging segment.
 * @param {string} jobId
 * @param {string} segmentId
 * @returns {string}
 */
function segmentAudioUrl(jobId, segmentId) {
  return `${API_BASE}/ingest/${jobId}/audio/${segmentId}`;
}

/**
 * Build the streaming URL for the source audio of an ingest job.
 * @param {string} jobId
 * @returns {string}
 */
function sourceAudioUrl(jobId) {
  return `${API_BASE}/ingest/${jobId}/source`;
}

/**
 * Trigger auto-detection of meow regions in the source audio.
 * @param {string} jobId
 * @returns {Promise<{ regions: Array<{ start_ms: number, end_ms: number }> }>}
 */
async function detectRegions(jobId) {
  return apiFetch(`/ingest/${jobId}/detect`, { method: 'POST' });
}

/**
 * Clip the source audio at the given regions and commit to the library.
 * @param {string} jobId
 * @param {Array<{ start_ms: number, end_ms: number }>} regions
 * @returns {Promise<{ meow_ids: string[] }>}
 */
async function clipAndCommit(jobId, regions) {
  return apiFetch(`/ingest/${jobId}/clip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regions }),
  });
}

/* ============================================================
   Stats & Labels
   ============================================================ */

/**
 * @returns {Promise<{
 *   total_meows: number,
 *   total_duration_ms: number,
 *   avg_duration_ms: number,
 *   most_played: object[],
 *   recent: object[],
 *   label_counts: object
 * }>}
 */
async function getStats() {
  return apiFetch('/stats');
}

/**
 * @returns {Promise<Array<{ label: string, count: number }>>}
 */
async function getLabels() {
  return apiFetch('/labels');
}

/* ============================================================
   Auth
   ============================================================ */

/**
 * @returns {Promise<{ authenticated: boolean, auth_required: boolean }>}
 */
async function getAuthStatus() {
  return apiFetch('/auth/status');
}

/**
 * @param {string} password
 * @returns {Promise<{ status: string }>}
 */
async function login(password) {
  return apiFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
}

/**
 * @returns {Promise<{ status: string }>}
 */
async function logout() {
  return apiFetch('/auth/logout', { method: 'POST' });
}

/* ============================================================
   Photos
   ============================================================ */

/**
 * @returns {Promise<{ items: object[] }>}
 */
async function getPhotos() {
  return apiFetch('/photos');
}

/**
 * @returns {Promise<object>} PhotoResponse with image_url
 */
async function getRandomPhoto(excludeId) {
  return apiFetch('/photos/random' + (excludeId ? '?exclude=' + encodeURIComponent(excludeId) : ''));
}

/**
 * @param {File} file
 * @returns {Promise<object>} PhotoResponse
 */
async function uploadPhoto(file) {
  const form = new FormData();
  form.append('file', file, file.name || 'photo.jpg');
  return apiFetch('/photos', { method: 'POST', body: form });
}

/**
 * @param {string} id
 * @returns {Promise<null>}
 */
async function deletePhoto(id) {
  return apiFetch(`/photos/${id}`, { method: 'DELETE' });
}
