"""Synthesised, royalty-free backing track on the beat grid, ducked under the voice, plus scene SFX."""
import hashlib, subprocess
import numpy as np

from .common import FFMPEG, SR, to_pcm

# chord = semitone offsets from the root; one chord per bar
MOODS = {
    "upbeat": dict(bpm=120, root=48, prog=[(0, 4, 7), (7, 11, 14), (9, 12, 16), (5, 9, 12)], kick="beats", snare=True, hat=2, arp=True),
    "hype":   dict(bpm=128, root=45, prog=[(0, 3, 7), (8, 12, 15), (3, 7, 10), (10, 14, 17)], kick="beats", snare=True, hat=4, arp=True),
    "calm":   dict(bpm=96,  root=48, prog=[(0, 4, 7), (5, 9, 12), (9, 12, 16), (7, 11, 14)], kick="half", snare=False, hat=0, arp=True),
    "cinematic": dict(bpm=90, root=45, prog=[(0, 3, 7), (-4, 0, 3), (-7, -3, 0), (-2, 2, 5)], kick="half", snare=False, hat=0, arp=False),
    "lofi":   dict(bpm=84, root=50, prog=[(0, 4, 11), (-3, 0, 7), (5, 9, 16), (7, 11, 17)], kick="half", snare=True, hat=2, arp=True),
    "dark":   dict(bpm=110, root=43, prog=[(0, 3, 7), (-2, 2, 5), (-4, 0, 3), (-5, -2, 2)], kick="half", snare=True, hat=2, arp=False),
}


def mood_bpm(mood: str) -> float:
    return MOODS[mood]["bpm"]


def _env(n, attack=0.005, decay=8.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t * decay)


def _tone(freq, dur, decay, harm=(1.0, 0.3, 0.1)):
    n = int(dur * SR); t = np.arange(n) / SR
    y = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harm))
    return y * _env(n, 0.004, decay)


def _add(buf, i, y):
    if i >= len(buf) or i < 0:
        return
    m = min(len(y), len(buf) - i)
    buf[i:i + m] += y[:m]


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def kick():
    n = int(0.25 * SR); t = np.arange(n) / SR
    ph = 2 * np.pi * (45 * t + 80 * (1 - np.exp(-t * 28)) / 28)
    return np.sin(ph) * np.exp(-t * 13) * 0.95


def snare(rng):
    n = int(0.18 * SR); t = np.arange(n) / SR
    return (rng.standard_normal(n) * 0.5 + np.sin(2 * np.pi * 190 * t) * 0.5) * np.exp(-t * 24) * 0.45


def hat(rng, open_=False):
    n = int((0.09 if open_ else 0.04) * SR); t = np.arange(n) / SR
    x = rng.standard_normal(n)
    x = np.diff(x, prepend=0)  # crude high-pass
    return x * np.exp(-t * (40 if open_ else 110)) * 0.16


def build_music(n_samples: int, mood: str, bpm: float, seed_text: str) -> np.ndarray:
    m = MOODS[mood]
    rng = np.random.default_rng(int(hashlib.sha1(seed_text.encode()).hexdigest()[:8], 16))
    beat = 60.0 / bpm
    out = np.zeros(n_samples, dtype=np.float32)      # drums
    ton = np.zeros(n_samples, dtype=np.float32)      # bass, pad, arp (pumped by the kick)
    nbeats = int(n_samples / SR / beat) + 2
    k = kick(); sn = snare(rng)
    arp_pat = [0, 1, 2, 1, 2, 1, 2, 0] if rng.random() < 0.5 else [0, 2, 1, 2, 0, 2, 1, 2]
    for b in range(nbeats):
        i = int(b * beat * SR)
        bar, pos = divmod(b, 4)
        chord = m["prog"][bar % 4]
        # drums
        if m["kick"] == "beats" or pos in (0, 2):
            _add(out, i, k * (1.0 if pos == 0 else 0.8))
        if m["snare"] and pos in (1, 3):
            _add(out, i, sn)
        if m["hat"]:
            for sub in range(m["hat"] // 2 or 1):
                _add(out, i + int((sub + 0.5) * beat / (m["hat"] // 2 or 1) * SR), hat(rng, open_=(sub == 0 and pos == 3)))
            if m["hat"] == 4:
                _add(out, i, hat(rng) * 0.6)
        # bass: root on beat 1 and the "and" of 2
        root = m["root"] + chord[0] - 12
        if pos == 0:
            _add(ton, i, _tone(midi(root), beat * 1.8, 2.2, (1.0, 0.35, 0.0)) * 0.55)
        if pos == 2:
            _add(ton, i + int(0.5 * beat * SR), _tone(midi(root + (7 if bar % 2 else 0)), beat * 0.9, 4, (1.0, 0.3, 0.0)) * 0.4)
        # pad on every bar start
        if pos == 0:
            for j, off in enumerate(chord):
                f = midi(m["root"] + 12 + off)
                for det in (-0.4, 0.4):  # slight detune for width
                    d = beat * 4
                    n = int(d * SR); t = np.arange(n) / SR
                    y = np.sin(2 * np.pi * f * (1 + det / 100) * t) + 0.25 * np.sin(4 * np.pi * f * t)
                    env = np.minimum(1, t / 0.08) * np.minimum(1, (d - t) / 0.25)
                    _add(ton, i, (y * env * 0.07).astype(np.float32))
        # arp: 8th notes
        if m["arp"]:
            for half in range(2):
                step = (b * 2 + half) % 8
                tone = chord[arp_pat[step] % 3] + 12
                _add(ton, i + int(half * beat / 2 * SR), _tone(midi(m["root"] + 12 + tone), beat * 0.45, 9, (1.0, 0.4, 0.15)) * 0.16)
    t = (np.arange(n_samples) / SR) % beat
    pump = 1 - 0.55 * np.exp(-t * 9) if m["kick"] == "beats" else 1 - 0.35 * np.exp(-((np.arange(n_samples) / SR) % (2 * beat)) * 6)
    return out + ton * pump.astype(np.float32)


# ───────────────────────── your own track ─────────────────────────
def load_track(path) -> np.ndarray:
    x = to_pcm(open(path, "rb").read()).astype(np.float32) / 32768
    peak = np.max(np.abs(x)) or 1.0
    return x / peak


def detect_beats(x: np.ndarray):
    """(bpm, seconds to the first beat, confidence 0-1) from onset strength. Good enough to cut on the beat."""
    x = x[: SR * 60]
    hop, n = 512, 2048
    nf = 1 + (len(x) - n) // hop
    if nf < 50:
        return 120.0, 0.0, 0.0
    idx = np.arange(n)[None, :] + hop * np.arange(nf)[:, None]
    spec = np.log1p(100 * np.abs(np.fft.rfft(x[idx] * np.hanning(n), axis=1)))
    flux = np.maximum(0, np.diff(spec, axis=0))
    def clean(e):
        e = np.maximum(0, e - np.convolve(e, np.ones(16) / 16, mode="same"))
        return np.convolve(e, np.array([0.25, 0.6, 1.0, 0.6, 0.25]), mode="same")   # peaks are 1 frame wide; widen them
    env = clean(flux.sum(axis=1))
    low = clean(flux[:, 1:8].sum(axis=1))      # < ~170 Hz: kicks, which sit on the beat in most music
    fr = SR / hop
    lag0 = (hop + n / 2) / SR       # env[k] describes the window centred at (k + 1) * hop + n / 2
    ac = np.fft.irfft(np.abs(np.fft.rfft(env, 2 * len(env))) ** 2)[: len(env)]
    best, bpm = -1, 120.0
    for b in np.arange(70, 180.5, 0.5):
        lag = 60 * fr / b
        i = int(lag); f = lag - i
        if i + 1 >= len(ac): continue
        v = (ac[i] * (1 - f) + ac[i + 1] * f) * np.exp(-0.5 * (np.log2(b / 120) / 0.9) ** 2)
        if v > best: best, bpm = v, float(b)
    # refine: the period that best lines up all onsets (sum over many beats is far sharper than one autocorr lag)
    def comb(b, ph=None):
        P = 60 * fr / b
        ks = np.arange(0, len(env) - P, P)
        phs = np.arange(0, P, 0.5) if ph is None else [ph]
        return max(env[np.clip((ks + q).astype(int), 0, len(env) - 1)].sum() for q in phs)
    bpm = float(max(np.arange(bpm - 1.5, bpm + 1.5, 0.05), key=comb))
    P = 60 * fr / bpm
    ks = np.arange(0, len(env) - P, P)
    phases = np.arange(0, P, 0.5)
    ph_env = (low / (low.max() or 1)) + 0.3 * (env / (env.max() or 1))   # kicks lead, everything else breaks ties
    scores = [ph_env[np.clip((ks + ph).astype(int), 0, len(env) - 1)].sum() for ph in phases]
    beat = 60 / bpm
    phase = float((phases[int(np.argmax(scores))] / fr + lag0) % beat)
    # confidence: share of strong kick onsets that sit on the half-beat grid, vs. what chance would give
    lo = low / (low.max() or 1)
    pk = [k for k in range(1, len(lo) - 1) if lo[k] > lo[k - 1] and lo[k] >= lo[k + 1] and lo[k] > np.percentile(lo, 97)]
    conf = 0.0
    if pk:
        t = np.array(pk) / fr + lag0
        dist = np.abs(((t - phase) / beat * 2 + 0.5) % 1 - 0.5) * beat / 2
        hit, chance = float(np.mean(dist < 0.04)), min(1.0, 0.16 / beat)
        conf = max(0.0, (hit - chance) / (1 - chance))
    return bpm, phase, conf


def fit_track(track, n, start):
    """Take n samples from `start` seconds, looping with a short crossfade if the track is too short."""
    i = int(start * SR)
    body = track[i:] if i < len(track) else track
    if len(body) >= n:
        return body[:n].copy()
    xf = int(0.5 * SR)
    out = body.copy()
    while len(out) < n:
        nxt = track
        fade = np.linspace(0, 1, xf, dtype=np.float32)
        out[-xf:] = out[-xf:] * (1 - fade) + nxt[:xf] * fade
        out = np.concatenate([out, nxt[xf:]])
    return out[:n]


def polish_voice(pcm: np.ndarray) -> np.ndarray:
    """Broadcast-style chain: rumble cut, less mud, more presence, gentle compression. Same length out."""
    af = ("highpass=f=85,equalizer=f=250:t=q:w=1.0:g=-2.5,equalizer=f=3200:t=q:w=1.2:g=3,"
          "equalizer=f=9000:t=q:w=1.0:g=1.5,acompressor=threshold=-21dB:ratio=3:attack=6:release=90:makeup=3")
    try:
        p = subprocess.run([FFMPEG, "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0", "-af", af,
                            "-f", "s16le", "-ar", str(SR), "-ac", "1", "pipe:1"], input=pcm.tobytes(), capture_output=True, check=True)
        out = np.frombuffer(p.stdout, dtype=np.int16)
    except Exception:
        return pcm
    if len(out) < len(pcm):
        out = np.concatenate([out, np.zeros(len(pcm) - len(out), np.int16)])
    return out[: len(pcm)]


def riser(dur=1.1, rng=None):
    rng = rng or np.random.default_rng(5)
    n = int(dur * SR); t = np.arange(n) / SR
    noise = rng.standard_normal(n).astype(np.float32)
    out = np.zeros(n, np.float32)
    # brighten over time: blend of smoothed (dark) and raw (bright) noise
    dark = np.convolve(noise, np.ones(40) / 40, mode="same")
    k = (t / dur) ** 2
    out = (dark * (1 - k) * 3 + noise * k * 0.6) * (t / dur) ** 1.6
    return out * 0.5


def duck_envelope(voice: np.ndarray) -> np.ndarray:
    """0..1 gain for the music: dips while the narrator speaks, recovers in the gaps."""
    x = np.abs(voice.astype(np.float32))
    win = int(0.06 * SR)
    env = np.convolve(x, np.ones(win) / win, mode="same")
    peak = np.percentile(env, 95) or 1.0
    speaking = np.clip(env / (peak * 0.35), 0, 1)
    rel = int(0.25 * SR)  # slow release so it doesn't pump
    sm = np.convolve(speaking, np.ones(rel) / rel, mode="same")
    return 1.0 - 0.68 * np.clip(sm * 1.4, 0, 1)


def whoosh(rng) -> np.ndarray:
    n = int(0.32 * SR); t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    # band-limited noise whose brightness rises then falls
    k = np.convolve(noise, np.ones(18) / 18, mode="same")
    env = np.sin(np.pi * np.clip(t / 0.32, 0, 1)) ** 2
    return (k * 3.0 * env * 0.5).astype(np.float32)


def thump():
    n = int(0.45 * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 52 * t) * np.exp(-t * 7) * 0.9).astype(np.float32)


def mix(voice: np.ndarray, scenes, mood: str, bpm: float, music: bool, seed_text: str, track=None, track_start=0.0,
        polish=True) -> np.ndarray:
    """voice: concatenated int16 narration. Returns int16 mix with music bed (ducked) and SFX."""
    n = len(voice)
    if polish:
        voice = polish_voice(voice)
    v = voice.astype(np.float32)
    rng = np.random.default_rng(3)
    bed = np.zeros(n, dtype=np.float32)
    if track is not None:
        mus = fit_track(track, n, track_start)
        vr = np.sqrt(np.mean((v / 32767) ** 2)) or 0.1
        mr = np.sqrt(np.mean(mus ** 2)) or 0.1
        bed = mus * (0.55 * vr / mr) * duck_envelope(voice) * 32767
        fade = int(0.8 * SR)
        bed[-fade:] *= np.linspace(1, 0, fade)
    elif music:
        bed = build_music(n, mood, bpm, seed_text)[:n] * duck_envelope(voice) * 32767 * 0.30
        fade = int(0.8 * SR)
        bed[-fade:] *= np.linspace(1, 0, fade)
    sfx = np.zeros(n, dtype=np.float32)
    for s in scenes:
        i = int(s.start * SR)
        if s.kind == "cta":
            _add(sfx, i, thump() * 32767 * 0.35)
            r = riser(rng=rng) * 32767 * 0.22
            _add(sfx, max(0, i - len(r)), r)
        _add(sfx, max(0, i - int(0.04 * SR)), whoosh(rng) * 32767 * 0.30)
    return np.clip(v + bed + sfx, -32768, 32767).astype(np.int16)
