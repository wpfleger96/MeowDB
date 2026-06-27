# Uniqueness Scoring Algorithm

This document describes the mathematics behind meowdb's audio fingerprinting and uniqueness scoring pipeline. The implementation lives in `src/meowdb/similarity.py`.

**Pipeline summary:** WAV file → 120-dimensional MFCC fingerprint → pairwise cosine similarity matrix → k-NN percentile-rank score (0–100).

---

## 1. Fingerprint Extraction

Each meow is represented as a 120-dimensional real-valued vector. The pipeline runs:
STFT → mel filterbank → PCEN → DCT (MFCCs) → delta coefficients → temporal aggregation.

### 1.1 Short-Time Fourier Transform

The audio is resampled to 44,100 Hz mono and normalized to the range [−1, 1]. A Hanning window is applied to each frame before the FFT to reduce spectral leakage:

$$w[n] = 0.5 \left(1 - \cos\!\left(\frac{2\pi n}{N-1}\right)\right), \quad n = 0, \ldots, N-1$$

Parameters: `n_fft = 2048`, `hop_length = 512`.

At 44,100 Hz this gives:
- Frame duration: 2048 / 44100 ≈ **46.4 ms**
- Hop duration: 512 / 44100 ≈ **11.6 ms**
- Frequency resolution: 44100 / 2048 ≈ **21.5 Hz/bin**

The one-sided power spectrum of frame $i$ is:

$$P_i[k] = \left|\text{FFT}(x_i \cdot w)[k]\right|^2, \quad k = 0, \ldots, \frac{N}{2}$$

### 1.2 Mel Filterbank

The mel scale compresses the frequency axis to approximate the human (and animal) auditory system's logarithmic frequency sensitivity. The conversion formulas are:

$$m = 2595 \cdot \log_{10}\!\left(1 + \frac{f}{700}\right) \qquad f = 700 \cdot \left(10^{m/2595} - 1\right)$$

`n_mels = 40` triangular filters are spaced linearly in mel between `fmin = 250 Hz` and `fmax = 8000 Hz`. For filter $m$ with center bin $c_m$ and edges $l_m$, $r_m$:

$$H_m[k] = \begin{cases} \dfrac{k - l_m}{c_m - l_m} & l_m \leq k < c_m \\[6pt] \dfrac{r_m - k}{r_m - c_m} & c_m \leq k < r_m \\[4pt] 0 & \text{otherwise} \end{cases}$$

The mel energy for frame $i$ and filter $m$ is:

$$E_i[m] = \sum_k H_m[k] \cdot P_i[k]$$

**Parameter rationale:** Cat fundamental frequency (F0) ranges from ~208 to ~1185 Hz (Sedova et al., 2025). Setting `fmin = 250 Hz` excludes purring (F0 ≈ 25–30 Hz) and environmental rumble. Setting `fmax = 8000 Hz` captures harmonics 5–8 of high-pitched meows. `n_mels = 40` provides more spectral resolution than the speech-recognition default of 26.

### 1.3 Per-Channel Energy Normalization (PCEN)

Rather than taking log-mel energies, we apply PCEN (Lostanlen et al., 2019), which adapts to local noise levels and compresses the dynamic range more robustly than a fixed log transform.

**Step 1 — IIR smoother** (per-channel, causal):

$$M_i[m] = (1 - s) \cdot M_{i-1}[m] + s \cdot E_i[m], \qquad M_0[m] = E_0[m]$$

The smoother tracks the local background energy envelope with time constant $1/s$.

**Step 2 — PCEN transform:**

$$\text{PCEN}_i[m] = \left(\frac{E_i[m]}{(\varepsilon + M_i[m])^\alpha} + \delta\right)^r - \delta^r$$

Parameters from Lostanlen et al. 2019: $s = 0.025$, $\alpha = 0.98$, $\delta = 2.0$, $r = 0.5$, $\varepsilon = 10^{-6}$.

PCEN has two advantages over log-mel for bioacoustic detection: (1) the adaptive denominator suppresses stationary background noise without a fixed noise floor assumption, and (2) the power-law compression $(\cdot)^r$ normalizes across loudness levels.

### 1.4 DCT and MFCC Extraction

The Mel-Frequency Cepstral Coefficients decorrelate the mel energies via a Type-II DCT with orthonormal normalization:

$$c_i[n] = \sqrt{\frac{2}{M}} \sum_{m=0}^{M-1} \text{PCEN}_i[m] \cdot \cos\!\left(\frac{\pi n (m + 0.5)}{M}\right)$$

with the $n=0$ coefficient scaled by $1/\sqrt{2}$ for orthonormality. Only the first `n_mfcc = 20` coefficients are retained. Lower coefficients capture the broad spectral shape (vocal tract filtering); higher coefficients capture fine spectral detail.

### 1.5 Delta Coefficients

Delta coefficients approximate the time derivative of each MFCC track, capturing temporal dynamics (onset/offset, pitch contour, modulation) that mean aggregation alone discards.

The N=2 regression estimator at frame $t$ is:

$$d_t = \frac{2c_{t+2} + c_{t+1} - c_{t-1} - 2c_{t-2}}{10}$$

This is the least-squares slope of a linear fit to the five frames $[t-2, t+2]$, which is both smoother and more temporally precise than a simple finite difference.

Boundary frames are handled by repeating the first/last frame (rather than zero-padding) to avoid artificial transients. For segments with fewer than 5 frames, deltas are set to zero — short meows lack enough temporal extent for meaningful derivatives.

Delta-delta coefficients are computed by applying the same formula to the delta sequence, capturing acceleration of spectral change.

### 1.6 Temporal Aggregation

For each of the three feature streams (static MFCCs, deltas, delta-deltas), we compute the mean and standard deviation across all frames:

$$\mu[\cdot] = \frac{1}{T}\sum_{t=1}^{T} f_t[\cdot], \qquad \sigma[\cdot] = \sqrt{\frac{1}{T}\sum_{t=1}^{T}(f_t[\cdot] - \mu[\cdot])^2}$$

The mean captures the average spectral shape; the standard deviation captures the degree of temporal variation. Concatenating all six vectors gives the fingerprint:

$$\mathbf{v} = [\mu_\text{static},\, \sigma_\text{static},\, \mu_\Delta,\, \sigma_\Delta,\, \mu_{\Delta\Delta},\, \sigma_{\Delta\Delta}] \in \mathbb{R}^{6 \times 20 = 120}$$

---

## 2. Uniqueness Scoring

Given the fingerprint matrix $X \in \mathbb{R}^{N \times 120}$ for a library of $N$ meows, uniqueness scores are computed in three steps: z-score normalization, cosine similarity, and percentile ranking.

A library of exactly one meow returns `None` — percentile rank is undefined with no peers.

### 2.1 Z-Score Normalization

Each feature dimension is standardized across the library:

$$\hat{X}_{ij} = \frac{X_{ij} - \mu_j}{\sigma_j}$$

where $\mu_j$ and $\sigma_j$ are the column mean and standard deviation. Features with $\sigma_j = 0$ (constant across all meows) are left as-is (denominator clamped to 1) to avoid division by zero.

**Key identity:** Z-score normalization followed by cosine similarity is algebraically equivalent to Pearson correlation. To see why: after z-scoring, each column has mean 0 and variance 1. Cosine similarity on L2-normalized rows of a zero-mean matrix is:

$$\cos(\hat{x}_i, \hat{x}_j) = \frac{\hat{x}_i \cdot \hat{x}_j}{\|\hat{x}_i\|\|\hat{x}_j\|}$$

Since each feature was mean-centered before normalization, this equals the Pearson correlation of the original feature vectors. The metric therefore measures spectral profile shape similarity, independent of volume or duration.

### 2.2 Cosine Similarity Matrix

Each row of the z-scored matrix is L2-normalized:

$$\tilde{X}_i = \frac{\hat{X}_i}{\|\hat{X}_i\|_2}$$

The full pairwise similarity matrix is then a single matrix multiply:

$$S = \tilde{X} \tilde{X}^\top \in \mathbb{R}^{N \times N}, \qquad S_{ij} \in [-1, 1]$$

$S_{ij} = 1$ means identical spectral profiles; $S_{ij} = -1$ means maximally anti-correlated profiles. This is O(N²·d) but for a personal library (N < 1000, d = 120) it is sub-millisecond on any modern CPU.

### 2.3 k-Nearest-Neighbor Averaging

Rather than using the single most-similar meow (fragile to one noisy entry), we average the top-$k$ similarity values. For each meow $i$:

1. Set $S_{ii} = -\infty$ (exclude self-similarity)
2. Find the $k$ largest values in row $i$, where $k = \min(k_\text{neighbors},\, N-1)$ (graceful degradation for small libraries)
3. Clamp each value to $[0, 1]$ (negative similarity — anti-correlated profiles — treated as zero contribution to the average)
4. Compute raw uniqueness:

$$u_i = 1 - \frac{1}{k}\sum_{j \in \text{top-}k} \text{clip}(S_{ij},\, 0,\, 1)$$

$u_i \in [0, 1]$: high values mean the meow is dissimilar from its nearest neighbors (more unique).

Default: `k_neighbors = 3`.

### 2.4 Percentile-Rank Transformation

The raw uniqueness values $u_i$ are mapped to percentile ranks within the library:

$$\text{score}_i = \frac{|\{j \neq i : u_j < u_i\}|}{N - 1} \times 100$$

This guarantees that scores use the full [0, 100] range regardless of the actual distribution of $u_i$ values. The least-unique meow always scores 0; the most-unique always scores 100. Scores are rounded to one decimal place.

**Note:** Percentile scores are relative to the library at computation time. Adding or removing meows changes every score — this is by design, and is consistent with the existing behavior of recomputing all scores on each add/delete.

---

## 3. Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `sr` | 44,100 Hz | CD-quality; preserves all meow harmonics |
| `n_fft` | 2048 | ~46 ms frames; good trade-off of time/freq resolution |
| `hop_length` | 512 | ~11.6 ms hop; ~4.4× overlap per frame |
| `fmin` | 250 Hz | Excludes purring (25–30 Hz) and low-frequency rumble |
| `fmax` | 8,000 Hz | Captures harmonics 5–8 of high-pitched meows |
| `n_mels` | 40 | More resolution than speech default (26); sub-YAMNet (64) |
| `n_mfcc` | 20 | More resolution than speech default (13) |
| PCEN `s` | 0.025 | Smoother time constant; from Lostanlen et al. 2019 |
| PCEN `α` | 0.98 | Gain normalization strength; from Lostanlen et al. 2019 |
| PCEN `δ` | 2.0 | Bias term for dynamic range compression; from Lostanlen et al. 2019 |
| PCEN `r` | 0.5 | Root compression exponent; from Lostanlen et al. 2019 |
| PCEN `ε` | 1e-6 | Numerical floor; prevents divide-by-zero |
| `k_neighbors` | 3 | k-NN averaging window; balances robustness vs. locality |

---

## 4. Known Limitations

**Short meow degeneration.** An 80 ms meow with `n_fft=2048` and `hop=512` at 44.1 kHz produces only ~1–3 STFT frames. Delta coefficients are set to zero when fewer than 5 frames are available, so short meows are compared only on their static MFCCs (40 of the 120 dimensions are informative; the rest are zero).

**Percentile instability with small libraries.** With N=2 meows, one scores 0 and one scores 100 regardless of how similar they are. Scores only become stable and meaningful around N ≥ 10. With N < k+1, `k` degrades to `N-1` automatically.

**Score drift on library changes.** Adding or deleting any meow recomputes all scores. A meow's score is a rank within the current library, not a fixed property of the audio.

**Cosine similarity concentration.** In high-dimensional spaces, pairwise cosine similarities concentrate near zero. At 120 dimensions this is less severe than the original 26-dim fingerprints, but the percentile-rank transformation is what ensures the full 0–100 range is used regardless.

**No magnitude sensitivity.** Z-score normalization + cosine similarity = Pearson correlation measures spectral shape, not loudness. Two meows with identical MFCC profiles but very different amplitudes score as identical.

---

## References

- Sedova et al. (2025). "Individual identification of domestic cats using vocal parameters of meow and purr." *Scientific Reports*, 15. — Cat F0 range, meow individuality statistics.
- Lostanlen et al. (2019). "Per-Channel Energy Normalization: Why and How." *IEEE Signal Processing Letters*, 26(1). — PCEN formula and parameter values.
- Davis & Mermelstein (1980). "Comparison of parametric representations for monosyllabic word recognition in continuously spoken sentences." *IEEE Transactions on ASSP*, 28(4). — Original MFCC derivation.
