"""Synthesised, royalty-free backing track on the beat grid, ducked under the voice, plus scene SFX."""
import hashlib
import numpy as np

from .common import SR

# chord = semitone offsets from the root; one chord per bar
MOODS = {
    "upbeat": dict(bpm=120, root=48, prog=[(0, 4, 7), (7, 11, 14), (9, 12, 16), (5, 9, 12)], kick="beats", snare=True, hat=2, arp=True),
    "hype":   dict(bpm=128, root=45, prog=[(0, 3, 7), (8, 12, 15), (3, 7, 10), (10, 14, 17)], kick="beats", snare=True, hat=4, arp=True),
    "calm":   dict(bpm=96,  root=48, prog=[(0, 4, 7), (5, 9, 12), (9, 12, 16), (7, 11, 14)], kick="half", snare=False, hat=0, arp=True),
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
    out = np.zeros(n_samples, dtype=np.float32)
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
            _add(out, i, _tone(midi(root), beat * 1.8, 2.2, (1.0, 0.35, 0.0)) * 0.55)
        if pos == 2:
            _add(out, i + int(0.5 * beat * SR), _tone(midi(root + (7 if bar % 2 else 0)), beat * 0.9, 4, (1.0, 0.3, 0.0)) * 0.4)
        # pad on every bar start
        if pos == 0:
            for j, off in enumerate(chord):
                f = midi(m["root"] + 12 + off)
                for det in (-0.4, 0.4):  # slight detune for width
                    d = beat * 4
                    n = int(d * SR); t = np.arange(n) / SR
                    y = np.sin(2 * np.pi * f * (1 + det / 100) * t) + 0.25 * np.sin(4 * np.pi * f * t)
                    env = np.minimum(1, t / 0.08) * np.minimum(1, (d - t) / 0.25)
                    _add(out, i, (y * env * 0.07).astype(np.float32))
        # arp: 8th notes
        if m["arp"]:
            for half in range(2):
                step = (b * 2 + half) % 8
                tone = chord[arp_pat[step] % 3] + 12
                _add(out, i + int(half * beat / 2 * SR), _tone(midi(m["root"] + 12 + tone), beat * 0.45, 9, (1.0, 0.4, 0.15)) * 0.16)
    return out


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


def mix(voice: np.ndarray, scenes, mood: str, bpm: float, music: bool, seed_text: str) -> np.ndarray:
    """voice: concatenated int16 narration. Returns int16 mix with music bed (ducked) and SFX."""
    n = len(voice)
    v = voice.astype(np.float32)
    rng = np.random.default_rng(3)
    bed = np.zeros(n, dtype=np.float32)
    if music:
        bed = build_music(n, mood, bpm, seed_text)[:n] * duck_envelope(voice) * 32767 * 0.30
        fade = int(0.8 * SR)
        bed[-fade:] *= np.linspace(1, 0, fade)
    sfx = np.zeros(n, dtype=np.float32)
    for s in scenes:
        i = int(s.start * SR)
        if s.kind == "cta":
            _add(sfx, i, thump() * 32767 * 0.35)
        _add(sfx, max(0, i - int(0.04 * SR)), whoosh(rng) * 32767 * 0.30)
    return np.clip(v + bed + sfx, -32768, 32767).astype(np.int16)
