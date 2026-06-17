/* ============================================================
   waveform.js — canvas mini-waveform renderer
   ~60 lines; no library dependency.
   ============================================================ */

/**
 * Draw a symmetrical bar waveform from a pre-computed amplitude array.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number[]} data  Normalized float array in [0, 1]
 * @param {string}   [color='#ff6b6b']  Bar color (CSS color string)
 * @param {number}   [progress=1]       Playback progress in [0, 1]; bars before
 *                                      this position are drawn in `color`, after
 *                                      in a dimmed version.
 */
function drawWaveform(canvas, data, color = '#ff6b6b', progress = 1) {
  if (!canvas || !data || data.length === 0) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth  || canvas.width;
  const cssH = canvas.clientHeight || canvas.height;

  // Resize backing store to match display pixels
  if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
    canvas.width  = cssW * dpr;
    canvas.height = cssH * dpr;
    ctx.scale(dpr, dpr);
  }

  ctx.clearRect(0, 0, cssW, cssH);

  const barCount = Math.min(data.length, Math.floor(cssW / 3)); // ~3px per bar+gap
  const barW = (cssW / barCount) * 0.6;
  const gap  = (cssW / barCount) * 0.4;
  const midY = cssH / 2;
  const maxBarH = midY * 0.95;

  // Down-sample data to barCount by taking the max of each bucket
  const bucketSize = data.length / barCount;

  for (let i = 0; i < barCount; i++) {
    const start = Math.floor(i * bucketSize);
    const end   = Math.floor((i + 1) * bucketSize);
    let amplitude = 0;
    for (let j = start; j < end; j++) {
      amplitude = Math.max(amplitude, data[j] || 0);
    }

    const barH = Math.max(2, amplitude * maxBarH);
    const x = i * (barW + gap);
    const played = (i / barCount) < progress;

    ctx.fillStyle = played ? color : dimColor(color, 0.25);
    ctx.beginPath();
    ctx.roundRect
      ? ctx.roundRect(x, midY - barH, barW, barH * 2, barW / 2)
      : ctx.rect(x, midY - barH, barW, barH * 2);
    ctx.fill();
  }
}

/**
 * Parse a CSS hex or rgb color and apply an opacity multiplier.
 * Returns an rgba() string.
 * @param {string} color
 * @param {number} alpha  0–1
 * @returns {string}
 */
function dimColor(color, alpha) {
  // Handle hex
  if (color.startsWith('#')) {
    const hex = color.slice(1);
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  // Fallback for any other format
  return color;
}

/**
 * Animate a waveform to show playback progress.
 * Returns a cancel function.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {number[]} data
 * @param {string} color
 * @param {() => number} getProgress  Returns current progress 0–1
 * @returns {() => void} cancel
 */
function animateWaveform(canvas, data, color, getProgress) {
  let rafId = null;
  let active = true;

  function frame() {
    if (!active) return;
    const p = getProgress();
    drawWaveform(canvas, data, color, p);
    rafId = requestAnimationFrame(frame);
  }

  rafId = requestAnimationFrame(frame);

  return function cancel() {
    active = false;
    if (rafId != null) cancelAnimationFrame(rafId);
    // Draw final state at progress=1 (fully colored)
    drawWaveform(canvas, data, color, 1);
  };
}
