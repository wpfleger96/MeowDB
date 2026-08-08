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
   Sounds
   ============================================================ */

/**
 * @param {{ sort?: string, label?: string, animal_id?: string, limit?: number, offset?: number }} [params]
 * @returns {Promise<{ items: object[], total: number, limit: number, offset: number }>}
 */
async function getSounds(params = {}) {
  const qs = new URLSearchParams();
  if (params.sort)       qs.set('sort',      params.sort);
  if (params.label)      qs.set('label',     params.label);
  if (params.animal_id)  qs.set('animal_id', params.animal_id);
  if (params.limit  != null) qs.set('limit',  String(params.limit));
  if (params.offset != null) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return apiFetch('/sounds' + (q ? '?' + q : ''));
}

/**
 * @param {string} [excludeId]
 * @param {string} [excludePhotoId]
 * @returns {Promise<object>} Sound object with mp3_url, waveform_data, animal_name, animal_species, photo
 */
async function getRandomSound(excludeId, excludePhotoId) {
  const qs = new URLSearchParams();
  if (excludeId)      qs.set('exclude',       excludeId);
  if (excludePhotoId) qs.set('exclude_photo', excludePhotoId);
  const q = qs.toString();
  return apiFetch('/sounds/random' + (q ? '?' + q : ''));
}

/**
 * @param {string} id
 * @param {{ labels?: string[], title?: string|null, recorded_at?: string|null }} fields
 * @returns {Promise<object>}
 */
async function updateSound(id, fields) {
  return apiFetch(`/sounds/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
}

/**
 * @param {string} id
 * @returns {Promise<null>}
 */
async function deleteSound(id) {
  return apiFetch(`/sounds/${id}`, { method: 'DELETE' });
}

/**
 * Record a play event (fire-and-forget — do not await in hot path).
 * @param {string} id
 * @returns {Promise<null>}
 */
async function recordPlay(id) {
  return apiFetch(`/sounds/${id}/play`, { method: 'POST' });
}

/**
 * Record or switch a feedback vote.
 * @param {string} id
 * @param {{ vote: 'up'|'down', previous?: 'up'|'down' }} body
 * @returns {Promise<null>}
 */
async function recordFeedback(id, body) {
  return apiFetch(`/sounds/${id}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/* ============================================================
   Version
   ============================================================ */

/**
 * @returns {Promise<{ version: string }>}
 */
async function getVersion() {
  return apiFetch('/version');
}

/* ============================================================
   Ingest / Upload
   ============================================================ */

/**
 * Upload an audio file and create an ingest job.
 * @param {File|Blob} file
 * @param {string} animalId
 * @returns {Promise<{ job_id: string, status: string }>}
 */
async function createIngestJob(file, animalId) {
  const form = new FormData();
  form.append('file', file, file.name || 'recording.webm');
  form.append('animal_id', animalId);
  return apiFetch('/ingest', { method: 'POST', body: form });
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
 * Trigger auto-detection of sound regions in the source audio.
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
 * @returns {Promise<{ sound_ids: string[] }>}
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
 *   total_sounds: number,
 *   total_duration_ms: number,
 *   avg_duration_ms: number,
 *   most_played: object[],
 *   recent: object[],
 *   label_counts: object,
 *   species_counts: object,
 *   first_sound_at: string|null
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
   Photos (global bootstrap only)
   ============================================================ */

/**
 * @returns {Promise<object>} PhotoResponse with image_url
 */
async function getRandomPhoto(excludeId) {
  return apiFetch('/photos/random' + (excludeId ? '?exclude=' + encodeURIComponent(excludeId) : ''));
}

/* ============================================================
   Animals
   ============================================================ */

/**
 * @returns {Promise<{ items: Array<{ id: string, name: string, species: string, created_at: string, sound_count: number, photo_count: number }> }>}
 */
async function getAnimals() {
  return apiFetch('/animals');
}

/**
 * @param {string} name
 * @param {string} species
 * @returns {Promise<object>}
 */
async function createAnimal(name, species) {
  return apiFetch('/animals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, species }),
  });
}

/**
 * @param {string} id
 * @returns {Promise<null>}
 */
async function deleteAnimal(id) {
  return apiFetch(`/animals/${id}`, { method: 'DELETE' });
}

/**
 * @param {string} animalId
 * @returns {Promise<{ items: object[] }>}
 */
async function getAnimalPhotos(animalId) {
  return apiFetch(`/animals/${animalId}/photos`);
}

/**
 * @param {string} animalId
 * @param {File} file
 * @returns {Promise<object>} PhotoResponse
 */
async function uploadAnimalPhoto(animalId, file) {
  const form = new FormData();
  form.append('file', file, file.name || 'photo.jpg');
  return apiFetch(`/animals/${animalId}/photos`, { method: 'POST', body: form });
}

/**
 * @param {string} animalId
 * @param {string} photoId
 * @returns {Promise<null>}
 */
async function deleteAnimalPhoto(animalId, photoId) {
  return apiFetch(`/animals/${animalId}/photos/${photoId}`, { method: 'DELETE' });
}

/**
 * @param {string} animalId
 * @param {string} photoId
 * @param {object} body
 * @returns {Promise<object>}
 */
async function editAnimalPhoto(animalId, photoId, body) {
  return apiFetch(`/animals/${animalId}/photos/${photoId}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * @param {string} animalId
 * @param {string} [excludeId]
 * @returns {Promise<object>} PhotoResponse
 */
async function getRandomAnimalPhoto(animalId, excludeId) {
  return apiFetch(
    `/animals/${animalId}/photos/random` +
    (excludeId ? '?exclude=' + encodeURIComponent(excludeId) : '')
  );
}

/* ============================================================
   Uniqueness
   ============================================================ */

/**
 * @param {{ force?: boolean }} [opts]
 * @returns {Promise<{ updated_count: number, elapsed_seconds: number }>}
 */
async function recalculateUniqueness({ force = false } = {}) {
  const qs = force ? '?force=true' : '';
  return apiFetch(`/uniqueness/recalculate${qs}`, { method: 'POST' });
}
