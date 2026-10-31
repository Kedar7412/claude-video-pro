"""Voice providers + word-level alignment.

auto        edge (3 tries) -> piper (offline) -> silent estimate. Default; never dies because one service is down
edge        free Microsoft neural voices, exact word boundaries (no key)
piper       offline neural voices (downloaded once to models/piper), words aligned with local Whisper
elevenlabs  character-level timestamps from the API (ELEVENLABS_API_KEY)
openai      OpenAI TTS (OPENAI_API_KEY) + local Whisper alignment
file        your own recording (--audio) + local Whisper alignment, sliced into scenes
none        silent; timings estimated (previews)
"""
import asyncio, base64, difflib, hashlib, io, json, os, re, sys, time, wave
from pathlib import Path
import numpy as np

from .common import SR, Scene, norm, pcm_to_16k_float, to_pcm

EDGE_PREFERRED = {
    "en": "en-US-AndrewMultilingualNeural", "es": "es-ES-AlvaroNeural", "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural", "it": "it-IT-DiegoNeural", "ru": "ru-RU-DmitryNeural", "el": "el-GR-NestorasNeural",
    "vi": "vi-VN-NamMinhNeural", "pl": "pl-PL-MarekNeural", "tr": "tr-TR-AhmetNeural", "uk": "uk-UA-OstapNeural",
}
GAP = 0.12  # seconds of silence after each scene's speech (beat padding adds a little more)


# ───────────────────────── alignment helpers ─────────────────────────
def align_words(script_words: list[str], timed: list[tuple], total: float) -> list[tuple]:
    """Map recognised/boundary words (text, start, end) onto the script's words by sequence matching.
    Unmatched script words get interpolated times between their matched neighbours."""
    a = [norm(w) for w in script_words]
    b = [norm(t[0]) for t in timed]
    res: list = [None] * len(a)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            res[blk.a + k] = (timed[blk.b + k][1], timed[blk.b + k][2])
    # interpolate gaps
    i = 0
    while i < len(res):
        if res[i] is not None:
            i += 1; continue
        j = i
        while j < len(res) and res[j] is None:
            j += 1
        left = res[i - 1][1] if i > 0 else (timed[0][1] if timed else 0.0)
        right = res[j][0] if j < len(res) else max(total, left + 0.2 * (j - i))
        step = (right - left) / (j - i)
        for k in range(i, j):
            res[k] = (left + (k - i) * step, left + (k - i + 1) * step)
        i = j
    # enforce monotonic, non-overlapping
    out, prev = [], 0.0
    for s, e in res:
        s = max(s, prev); e = max(e, s + 0.05); out.append((s, e)); prev = s
    return out


def estimate_times(words: list[str], speech: float) -> list[tuple]:
    weights = [len(norm(w)) + 2 for w in words]
    total, acc, out = sum(weights), 0.0, []
    for w in weights:
        out.append((acc / total * speech, (acc + w) / total * speech)); acc += w
    return out


def log(msg): print(msg, file=sys.stderr, flush=True)


_whisper = {}
_whisper_failed = False
def whisper_name(lang): return "tiny.en" if lang == "en" else "base"


def transcribe_words(pcm: np.ndarray, lang: str):
    """Local Whisper (faster-whisper) word timestamps. Returns None (-> estimated timing) if the model is unavailable."""
    global _whisper_failed
    if _whisper_failed:
        return None
    try:
        from faster_whisper import WhisperModel
        name = whisper_name(lang)
        if name not in _whisper:
            log(f"    loading Whisper '{name}' (first run downloads it; run `reel.py --setup` to do this ahead of time)")
            _whisper[name] = WhisperModel(name, device="cpu", compute_type="int8")
        segs, _ = _whisper[name].transcribe(pcm_to_16k_float(pcm), language=lang, word_timestamps=True,
                                            vad_filter=False, beam_size=1)
        return [(w.word.strip(), w.start, w.end) for sg in segs for w in (sg.words or [])]
    except Exception as e:
        _whisper_failed = True
        log(f"    ! Whisper unavailable ({type(e).__name__}); captions for this run use estimated timing")
        return None


# ───────────────────────── offline voices (piper) ─────────────────────────
MODELS = Path(__file__).resolve().parent.parent / "models" / "piper"
PIPER_VOICES = {   # lang -> path under huggingface.co/rhasspy/piper-voices
    "en": "en/en_US/lessac/medium/en_US-lessac-medium", "es": "es/es_ES/davefx/medium/es_ES-davefx-medium",
    "fr": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium", "de": "de/de_DE/thorsten/medium/de_DE-thorsten-medium",
    "pt": "pt/pt_BR/faber/medium/pt_BR-faber-medium", "it": "it/it_IT/paola/medium/it_IT-paola-medium",
    "ru": "ru/ru_RU/dmitri/medium/ru_RU-dmitri-medium",
}
_piper = {}


def ensure_piper(lang: str) -> Path:
    import requests
    rel = PIPER_VOICES.get(lang)
    if not rel:
        raise RuntimeError(f"no offline voice mapped for language '{lang}'")
    MODELS.mkdir(parents=True, exist_ok=True)
    onnx = MODELS / (rel.split("/")[-1] + ".onnx")
    for ext in ("", ".json"):
        dst = Path(str(onnx) + ext)
        if not dst.exists():
            log(f"    downloading offline voice {dst.name} (one time)")
            r = requests.get(f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{rel}.onnx{ext}", timeout=300)
            r.raise_for_status()
            dst.write_bytes(r.content)
    return onnx


def tts_piper(text: str, lang: str) -> bytes:
    from piper import PiperVoice
    onnx = ensure_piper(lang)
    if lang not in _piper:
        _piper[lang] = PiperVoice.load(str(onnx))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        _piper[lang].synthesize_wav(text, w)
    return buf.getvalue()


# ───────────────────────── cache ─────────────────────────
CACHE = Path(__file__).resolve().parent.parent / ".cache" / "tts"


def cached(key_parts, fn):
    """fn() -> (pcm int16, timed or None). Re-runs reuse the result, so iterating on visuals needs no network."""
    key = hashlib.sha1("|".join(map(str, key_parts)).encode()).hexdigest()
    f = CACHE / f"{key}.npz"
    if f.exists():
        d = np.load(f, allow_pickle=False)
        t = json.loads(str(d["timed"]))
        return d["pcm"], (t if t else None)
    pcm, timed = fn()
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez(f, pcm=pcm, timed=json.dumps(timed or []))
    return pcm, timed


# ───────────────────────── providers ─────────────────────────
async def _edge_async(text, voice, rate):
    import edge_tts
    c = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    audio, words = b"", []
    async for ch in c.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
    return audio, words


def pick_edge_voice(lang: str, voice: str) -> str:
    if voice:
        return voice
    return EDGE_PREFERRED.get(lang, EDGE_PREFERRED["en"])


def tts_elevenlabs(text, voice):
    import requests
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice or '21m00Tcm4TlvDq8ikWAM'}/with-timestamps",
                      headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                      json={"text": text, "model_id": "eleven_multilingual_v2"}, timeout=120)
    r.raise_for_status()
    j = r.json()
    al = j["alignment"]
    words, cur, st, en = [], "", None, None
    for ch, s, e in zip(al["characters"], al["character_start_times_seconds"], al["character_end_times_seconds"]):
        if ch.isspace():
            if cur: words.append((cur, st, en)); cur, st = "", None
        else:
            if st is None: st = s
            cur += ch; en = e
    if cur: words.append((cur, st, en))
    return base64.b64decode(j["audio_base64"]), words


def tts_openai(text, voice):
    import requests
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                      json={"model": "gpt-4o-mini-tts", "voice": voice or "alloy", "input": text,
                            "response_format": "mp3"}, timeout=120)
    r.raise_for_status()
    return r.content


def _finish(s: Scene, pcm: np.ndarray, timed, source: str):
    """Trim leading silence so the first word lands almost immediately, then store audio + word times."""
    lead = 0.0
    if timed:
        lead = max(0.0, min(timed[0][1] - 0.06, 0.5))
        if s.kind != "hook":  # keep a little breath before non-hook scenes
            lead = max(0.0, lead - 0.04)
    cut = int(lead * SR)
    if timed:   # drop the provider's trailing silence too, keeping a short natural tail
        end = int(min(len(pcm), (timed[-1][2] + 0.14) * SR))
        pcm = pcm[:max(end, cut + 1)]
    pcm = pcm[cut:]
    s.speech = len(pcm) / SR
    s.audio = np.concatenate([pcm, np.zeros(int(GAP * SR), dtype=np.int16)])
    if timed:
        shifted = [(max(0.0, t[1] - lead), max(0.0, t[2] - lead)) for t in timed]
        s.word_times = align_words(s.words, [(t[0], a, b) for t, (a, b) in zip(timed, shifted)], s.speech)
        s.timing_source = source


def _edge_retry(text, voice, lang, rate, tries=8):   # the free service drops a share of requests; retry quickly
    last = None
    for k in range(tries):
        try:
            audio, timed = asyncio.run(_edge_async(text, pick_edge_voice(lang, voice), rate))
            if not audio:
                raise RuntimeError("empty audio")
            return to_pcm(audio), timed
        except Exception as e:
            last = e
            time.sleep(min(3.0, 0.6 * (k + 1)))
    raise RuntimeError(f"edge TTS failed after {tries} tries: {last}")


def _piper_one(text, lang):
    pcm = to_pcm(tts_piper(text, lang))
    return pcm, transcribe_words(pcm, lang)


def _one(s: Scene, provider, voice, lang, wpm, rate):
    """Returns (pcm, timed, source_label)."""
    if provider == "none":
        secs = max(1.4, len(s.words) * 60 / wpm + 0.3)
        return np.zeros(int(secs * SR), dtype=np.int16), None, "estimated"
    if provider == "edge":
        pcm, t = cached(("edge", pick_edge_voice(lang, voice), rate, s.text), lambda: _edge_retry(s.text, voice, lang, rate))
        return pcm, t, "edge word boundaries"
    if provider == "piper":
        pcm, t = cached(("piper", lang, s.text), lambda: _piper_one(s.text, lang))
        return pcm, t, "offline voice + whisper alignment" if t else "estimated"
    if provider == "elevenlabs":
        def go():
            a, t = tts_elevenlabs(s.text, voice); return to_pcm(a), t
        pcm, t = cached(("eleven", voice, s.text), go)
        return pcm, t, "elevenlabs timestamps"
    if provider == "openai":
        def go():
            p = to_pcm(tts_openai(s.text, voice)); return p, transcribe_words(p, lang)
        pcm, t = cached(("openai", voice, s.text), go)
        return pcm, t, "whisper alignment" if t else "estimated"
    raise SystemExit(f"unknown tts provider {provider}")


def synthesize(scenes: list[Scene], provider: str, voice: str, lang: str, wpm: int, rate: str, audio_path=None):
    if provider == "file":
        return _from_recording(scenes, audio_path, lang)
    chain = ["edge", "piper", "none"] if provider == "auto" else [provider]
    for k, prov in enumerate(chain):
        try:
            results = [_one(s, prov, voice, lang, wpm, rate) for s in scenes]   # all scenes, one voice
            break
        except Exception as e:
            if k == len(chain) - 1:
                raise
            log(f"    ! {prov} failed ({e}); using {chain[k + 1]} for every scene so the voice stays the same")
    for s, (pcm, timed, src) in zip(scenes, results):
        if prov == "none":
            s.speech = len(pcm) / SR
            s.audio = np.concatenate([pcm, np.zeros(int(GAP * SR), dtype=np.int16)])
            s.timing_source = "estimated"
        else:
            _finish(s, pcm, timed, src)


def setup(langs):
    """Download everything that would otherwise happen on first use."""
    from faster_whisper import WhisperModel
    for lang in langs:
        log(f"[{lang}] Whisper model '{whisper_name(lang)}' ...")
        WhisperModel(whisper_name(lang), device="cpu", compute_type="int8")
        log(f"[{lang}] offline voice ...")
        try: ensure_piper(lang)
        except Exception as e: log(f"    ! {e}")
    try:
        asyncio.run(_edge_async("ok", pick_edge_voice(langs[0], ""), "+0%")); log("edge voices: reachable")
    except Exception as e:
        log(f"edge voices: NOT reachable ({e}); the offline voice will be used")


def _from_recording(scenes, path, lang):
    """Align the whole script against a user recording, then slice the audio into scenes."""
    pcm = to_pcm(open(path, "rb").read())
    timed = transcribe_words(pcm, lang)
    if timed is None:
        raise SystemExit('--tts file needs Whisper to align your recording; run `python reel.py --setup`')
    all_words = [w for s in scenes for w in s.words]
    times = align_words(all_words, timed, len(pcm) / SR)
    k = 0
    bounds = []
    for s in scenes:
        bounds.append((times[k][0], times[k + len(s.words) - 1][1])); k += len(s.words)
    cuts = [0.0] + [(bounds[i][1] + bounds[i + 1][0]) / 2 for i in range(len(scenes) - 1)] + [len(pcm) / SR]
    k = 0
    for i, s in enumerate(scenes):
        a = max(cuts[i], bounds[i][0] - 0.12) if i else max(0.0, bounds[i][0] - 0.06)
        b = cuts[i + 1]
        seg = pcm[int(a * SR):int(b * SR)]
        rel = [(max(0, t0 - a), max(0, t1 - a)) for t0, t1 in times[k:k + len(s.words)]]; k += len(s.words)
        s.speech = bounds[i][1] - a
        s.audio = np.concatenate([seg[: int((s.speech + GAP) * SR)],
                                  np.zeros(max(0, int((s.speech + GAP) * SR) - len(seg)), dtype=np.int16)])
        s.word_times = rel; s.timing_source = "whisper alignment (your recording)"
