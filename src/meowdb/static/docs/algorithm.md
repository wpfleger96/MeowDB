# MeowDB Audio Algorithms

MeowDB's audio pipeline has two independent stages, documented in the two parts below:

- **Part 1 — Segment Detection** (`src/meowdb/processor.py`): finds the regions of a recording that contain the selected species' vocalizations.
- **Part 2 — Uniqueness Scoring** (`src/meowdb/similarity.py`): fingerprints each detected clip and scores how unique it is within the library.

Detection is species-specific: the user picks the animal, and the detector finds that species' primary calls (cats: meows and trills; dogs: barks, howls, whines). There is no species classification from audio.

---

# Part 1 — Segment Detection

Detection runs a shared energy-based voice-activity pipeline followed by a species-specific classifier: the **tonal** profile (cats) and the **canine** profile (dogs). All stages operate on audio resampled to 44,100 Hz mono, normalized to [−1, 1].

**Pipeline summary:** audio → Butterworth band filters → framewise RMS dB envelope → adaptive threshold → gap fill → duration filter → species classifier → padding/merge.

## 1. Shared Segmentation Pipeline

### 1.1 Band Filtering

Two 4th-order Butterworth filters produce the signals every later stage consumes. The **detection band** isolates the species' vocal energy; the **reference band** captures complementary energy for the classifier's ratio tests:

$$x_\text{det} = \text{bandpass}(x,\ f_\text{low},\ f_\text{high}) \qquad x_\text{ref} = \begin{cases} \text{lowpass}(x,\ 250\ \text{Hz}) & \text{cat} \\[4pt] \text{highpass}(x,\ 4500\ \text{Hz}) & \text{dog} \end{cases}$$

The detection band is 250–8000 Hz for cats and 150–3500 Hz for dogs. Why the reference band points in opposite directions for the two species is the subject of §2 and §3.

### 1.2 RMS Energy Envelope

Voice activity is measured on a framewise RMS envelope of the detection band, using **10 ms frames** and a **5 ms hop**. The squared signal is convolved with a 10 ms boxcar, square-rooted, converted to dB, and sampled at the hop rate:

$$\text{rms}[n] = \sqrt{\frac{1}{W}\sum_{|m| \leq W/2} x_\text{det}[n+m]^2}, \qquad L[n] = 20 \log_{10}\!\left(\text{rms}[n] + 10^{-10}\right)$$

where $W$ is 10 ms of samples (441 at 44.1 kHz), centered on sample $n$. The same envelope is reused by the canine classifier's rise-time test (§3.5), so both stages see identical energy contours.

### 1.3 Adaptive Threshold

Frames above −80 dBFS are considered *active* (everything below is digital silence and excluded from statistics). The noise floor is estimated as the 30th percentile $P_{30}$ of the active frame levels, and the silence threshold is set 10 dB above it, clamped to a fixed operating window:

$$\theta = \operatorname{clip}\!\left(P_{30} + 10\ \text{dB},\ -45,\ -40\right)\ \text{dBFS}$$

The floor (−45 dBFS) prevents very quiet recordings from pulling the threshold down into the noise; the ceiling (−40 dBFS) prevents loud, busy backgrounds from swallowing genuine calls. If fewer than 10 active frames exist, a fixed −40 dBFS threshold is used instead. Frames with $L[n] \geq \theta$ are marked non-silent.

### 1.4 Gap Fill and Duration Filter

Silence runs shorter than `min_silence_ms` (cat: 150 ms, dog: 250 ms) are filled — treated as non-silent — so brief intra-call dips do not split one vocalization into fragments. The longer dog value deliberately merges a bark *volley* into a single segment: one clip per volley, not one clip per bark.

Contiguous non-silent runs become candidate segments. Candidates outside [`min_segment_ms`, `max_segment_ms`] are **dropped, not truncated**: cat 80–5000 ms; dog 60–15,000 ms. The dog bounds admit a single short bark at one end and multi-second howl bouts at the other — under the cat ceiling of 5000 ms a long howl would be silently discarded at this stage.

### 1.5 Padding and Merge

Segments that survive classification (§2–§3) are padded by 200 ms on each side for listening context, clamped to the file boundaries. Padded segments that overlap are merged, keeping the maximum energy ratio of the merged group.

## 2. Cat Classifier ("tonal")

The cat reference band — lowpass below 250 Hz — is a genuine cat-vs-speech discriminator: adult speech F0 and low-frequency rumble live below 250 Hz, while meows (F0 ≈ 208–1185 Hz [1]) put almost no energy there. A candidate segment $[s, e)$ is accepted iff **all three** tests pass (AND):

**Test 1 — whole-segment average ratio.** Detection-band RMS must dominate the reference band:

$$R_\text{avg} = \frac{\text{rms}(x_\text{det}[s{:}e])}{\text{rms}(x_\text{ref}[s{:}e]) + 10^{-10}} \geq 3.0$$

**Test 2 — peak windowed ratio.** The same ratio computed over sliding **50 ms** windows (50% hop); the maximum across windows must satisfy

$$R_\text{peak} = \max_{w} \frac{\text{rms}(x_\text{det}[w])}{\text{rms}(x_\text{ref}[w]) + 10^{-10}} \geq 3.5$$

This rescues short meows whose whole-segment average is diluted by surrounding noise.

**Test 3 — spectral flatness.** Meows are tonal; broadband noise is flat. Spectral flatness is the ratio of geometric to arithmetic mean of the power spectrum over the in-band bins:

$$\text{SF} = \frac{\exp\!\left(\dfrac{1}{K} \displaystyle\sum_{k \in B} \ln P_k\right)}{\dfrac{1}{K} \displaystyle\sum_{k \in B} P_k} \leq 0.45$$

where $P_k$ is the power spectrum of a 2048-sample Hann window, $B$ is the set of $K$ FFT bins inside the detection band, and SF is averaged over consecutive windows spanning the segment. SF → 1 for white noise, SF → 0 for a pure tone.

## 3. Dog Classifier ("canine")

### 3.1 Why the cat design fails for dogs

Porting the tonal profile to a dog band breaks in three ways:

1. **Degenerate reference band.** With a dog band starting at 60 Hz, the lowpass-below-band reference sits below 60 Hz — where real recordings have essentially no energy. The reference RMS collapses toward zero, so both ratio tests divide by (nearly) nothing and pass *everything*: speech, music, door slams.
2. **Inverted tonality test.** Flatness ≤ 0.45 ("calls are tonal") rejects broadband barks while passing harmonic speech vowels — the pipeline would preferentially select speech and discard barks.
3. **Speech overlap.** The speech band (300–3400 Hz) sits *inside* the dog detection band, so no energy ratio alone can separate speech from barks. Discrimination must come from temporal and harmonic structure instead.

### 3.2 Bands

The detection band is **150–3500 Hz** — not 60–3500: growls are out of scope, and 60–150 Hz admits HVAC rumble and handling thumps into the VAD. The reference band flips to a **highpass at ≥ 4500 Hz**, leaving a 1 kHz guard gap above 3500 Hz so the 4th-order Butterworth skirts don't leak species energy into the reference. (This is always well-defined: input audio is resampled to 44.1 kHz, so Nyquist is 22.05 kHz.)

Note the fingerprint band used in Part 2 keeps `fmin = 60` / `fmax = 3500` for dogs — the *detection* band and the *fingerprint* band intentionally diverge.

### 3.3 Decision Structure

A candidate is accepted iff it passes an in-band dominance gate **and** at least one of two call-shape branches:

$$\text{accept} = G \ \land\ (A \lor B)$$

### 3.4 Gate G — In-Band Dominance

$$G:\quad \frac{\text{rms}(x_\text{det}[s{:}e])}{\text{rms}(x_\text{ref}[s{:}e]) + 10^{-10}} \geq 2.0$$

This dominance ratio is what `species_energy_ratio` stores for dog clips. It rejects broadband non-vocal sound — full-band white noise scores ≈ 0.44 — while voiced dog calls concentrate their energy in-band and score ≥ 5–10. The gate is deliberately weak against speech (speech also passes it); speech rejection is the branches' job.

### 3.5 Branch A — Impulsive (bark)

1. **Rise time.** From the segment's 10 ms / 5 ms RMS dB envelope (§1.2), measure the time from the last frame at or below $\text{peak} - 20\ \text{dB}$ to the peak frame; require it to be **≤ 40 ms**. Barks reach peak energy in 5–20 ms; speech vowels build over 50–150 ms.
2. **Broadband check.** In-band spectral flatness (same estimator as §2, Test 3) must be **≥ 0.20**. This is the anti-speech cue: a stressed vowel can attack fast, but it is never broadband — vowels measure ≈ 0.05–0.15.

### 3.6 Branch B — Tonal Sustained (howl/whine)

1. **Tonality.** Spectral flatness **≤ 0.30** — tighter than the cat's 0.45, because the band is narrower and Branch B carries more of the speech-rejection burden.
2. **Duration.** Unpadded duration **≥ 300 ms** (speech syllables run 100–250 ms with pitch resets between them).
3. **Harmonicity and pitch floor.** Per 2048-sample Hann window (hop 1024), the FFT-based normalized autocorrelation $r[\tau]/r[0]$ is searched over lags corresponding to F0 ∈ 150–2000 Hz:

$$H = \max_{\tau \in [\,f_s/2000,\ f_s/150\,]} \frac{r[\tau]}{r[0]}$$

A frame is *voiced* if $H \geq 0.4$, with per-frame pitch estimate $F_0 = f_s / \tau^*$. The branch requires:

- voiced fraction ≥ 0.5 (at least half the frames voiced),
- mean harmonicity over voiced frames ≥ 0.5,
- **median voiced F0 ≥ 250 Hz.**

### 3.7 Speech Rejection

Adult speech F0 spans 85–255 Hz and syllables last 100–250 ms. Speech fails Branch A on the flatness floor (harmonic vowels ≈ 0.05–0.15, well under 0.20) and fails Branch B twice: the 300 ms sustained-tonal requirement, and the F0 floor (median speech F0 falls below 250 Hz). Barks pass Branch A; howls and whines pass Branch B.

### 3.8 Known Limitation — Deep Howls

The 250 Hz median-F0 floor is a deliberate trade-off: a deep howl with F0 below 250 Hz and no sharp onset fails both branches and is **missed**. Most howls sit at ≥ 300 Hz and whines at 400–2000 Hz, and false speech clips in a dog library are worse than an occasional missed low howl — but the miss is real and documented here.

## 4. Parameters

Shared VAD machinery (both species): 10 ms frames / 5 ms hop, adaptive threshold $\theta = \operatorname{clip}(P_{30} + 10\ \text{dB},\ -45,\ -40)$ dBFS, 200 ms pre/post padding.

| Parameter | Cat ("tonal") | Dog ("canine") | Rationale |
|-----------|---------------|----------------|-----------|
| `classifier` | `tonal` | `canine` | Species classifier profile |
| `band_low_hz` | 250 Hz | 150 Hz | Cat: excludes speech F0 and rumble; dog: excludes HVAC rumble (growls out of scope) |
| `band_high_hz` | 8,000 Hz | 3,500 Hz | Cat: harmonics 5–8 of high meows; dog: bark/howl energy ceiling |
| Reference band | lowpass < 250 Hz | highpass ≥ 4,500 Hz | Cat: speech/rumble detector; dog: 1 kHz guard gap above the detection band |
| `min_silence_ms` | 150 | 250 | Dog: merges a bark volley into one segment |
| `min_segment_ms` | 80 | 60 | Dog: admits a single short bark |
| `max_segment_ms` | 5,000 | 15,000 | Dog: howl bouts; over-long candidates are dropped, not truncated |
| `min_species_energy_ratio` | 3.0 | — | Test 1: whole-segment average ratio |
| `min_peak_ratio` | 3.5 | — | Test 2: peak 50 ms windowed ratio |
| `peak_ratio_window_ms` | 50 | — | Test 2 window length |
| `max_spectral_flatness` | 0.45 | — | Test 3: tonality ceiling |
| `min_band_dominance_ratio` | — | 2.0 | Gate G: in-band dominance |
| `max_attack_ms` | — | 40 | Branch A: rise time from peak − 20 dB to peak |
| `min_impulsive_flatness` | — | 0.20 | Branch A: broadband floor (anti-speech) |
| `max_tonal_flatness` | — | 0.30 | Branch B: tonality ceiling |
| `min_tonal_ms` | — | 300 | Branch B: sustained duration (speech syllables 100–250 ms) |
| `min_harmonicity` | — | 0.5 | Branch B: mean voiced harmonicity |
| `min_voiced_fraction` | — | 0.5 | Branch B: fraction of voiced frames |
| `min_tonal_f0_hz` | — | 250 Hz | Branch B: median-F0 floor (adult speech F0 is 85–255 Hz) |
| `max_tonal_f0_hz` | — | 2,000 Hz | Branch B: F0 search ceiling (whines reach 2 kHz) |

---

# Part 2 — Uniqueness Scoring

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

**Parameter rationale:** Cat fundamental frequency (F0) ranges from ~208 to ~1185 Hz [1]. Setting `fmin = 250 Hz` excludes purring (F0 ≈ 25–30 Hz) and environmental rumble. Setting `fmax = 8000 Hz` captures harmonics 5–8 of high-pitched meows. `n_mels = 40` provides more spectral resolution than the speech-recognition default of 26.

### 1.3 Per-Channel Energy Normalization (PCEN)

Rather than taking log-mel energies, we apply PCEN [2], which adapts to local noise levels and compresses the dynamic range more robustly than a fixed log transform.

**Step 1 — IIR smoother** (per-channel, causal):

$$M_i[m] = (1 - s) \cdot M_{i-1}[m] + s \cdot E_i[m], \qquad M_0[m] = E_0[m]$$

The smoother tracks the local background energy envelope with time constant $1/s$.

**Step 2 — PCEN transform:**

$$\text{PCEN}_i[m] = \left(\frac{E_i[m]}{(\varepsilon + M_i[m])^\alpha} + \delta\right)^r - \delta^r$$

Parameters from [2]: $s = 0.025$, $\alpha = 0.98$, $\delta = 2.0$, $r = 0.5$, $\varepsilon = 10^{-6}$.

PCEN has two advantages over log-mel for bioacoustic detection: (1) the adaptive denominator suppresses stationary background noise without a fixed noise floor assumption, and (2) the power-law compression $(\cdot)^r$ normalizes across loudness levels.

### 1.4 DCT and MFCC Extraction

The Mel-Frequency Cepstral Coefficients [3] decorrelate the mel energies via a Type-II DCT with orthonormal normalization:

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
| PCEN `s` | 0.025 | Smoother time constant; from [2] |
| PCEN `α` | 0.98 | Gain normalization strength; from [2] |
| PCEN `δ` | 2.0 | Bias term for dynamic range compression; from [2] |
| PCEN `r` | 0.5 | Root compression exponent; from [2] |
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

1. Sedova et al. (2025). "Individual identification of domestic cats using vocal parameters of meow and purr." *Scientific Reports*, 15. — Cat F0 range, meow individuality statistics.
2. Lostanlen et al. (2019). "Per-Channel Energy Normalization: Why and How." *IEEE Signal Processing Letters*, 26(1). — PCEN formula and parameter values.
3. Davis & Mermelstein (1980). "Comparison of parametric representations for monosyllabic word recognition in continuously spoken sentences." *IEEE Transactions on ASSP*, 28(4). — Original MFCC derivation.
