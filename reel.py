#!/usr/bin/env python3
"""Topic or script -> voice -> aligned captions -> beat-synced 1080x1920 reel + caption, SRT, poster, review sheets.

  python reel.py script.txt                       # your script (blank line = new scene)
  python reel.py --topic "why sleep matters"      # LLM writes it (ANTHROPIC_API_KEY or OPENAI_API_KEY)
  python reel.py --topic "my topic" --points "one;two;three"   # no key: your points, hook formula + CTA added
  python reel.py script.txt --formats 9:16,1:1,16:9            # all aspect ratios from one timeline
  python reel.py script.txt --broll-dir my_clips/              # footage style from your own clips
  python reel.py script.txt --music-file track.mp3             # cut on the beats of your own track
  python reel.py --setup                                       # pre-download Whisper + offline voice
Footage style uses Pexels stock video when PEXELS_API_KEY is set (environment or .env file).
"""
import argparse, json, math, os, re, subprocess, sys, tempfile, wave
from pathlib import Path

import numpy as np

from reelkit import figures, footage, looks, music, musicsearch, script as scriptmod, voice
from reelkit.checks import load_history, originality, run_gates, save_history
from reelkit.common import FFMPEG, FORMATS, FPS, SR, Scene
from reelkit.kinetic import ACCENTS, FootageRenderer
from reelkit.render import PALETTES, Renderer

ROOT = Path(__file__).resolve().parent


for _stream in (sys.stdout, sys.stderr):   # Windows consoles default to a legacy codepage
    try: _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass


def log(msg): print(msg, file=sys.stderr, flush=True)


def load_env(path):
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def compute_timing(scenes, bpm):
    """Pad every scene to whole half-beats so each cut lands on the music grid; estimate word times if none."""
    beat = 30.0 / bpm
    t = 0.0
    for s in scenes:
        if not s.word_times:
            s.word_times = voice.estimate_times(s.words, s.speech)
        n = len(s.audio)
        beats = math.ceil(n / SR / beat - 1e-6)
        s.audio = np.concatenate([s.audio, np.zeros(int(round(beats * beat * SR)) - n, dtype=np.int16)])
        s.start, s.dur = t, len(s.audio) / SR
        t += s.dur
    return t


def write_wav(path, pcm):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


def render_video(scenes, renderer, out: Path, total, mix_pcm, blur, preset="medium"):
    W, H = renderer.W, renderer.H
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"; write_wav(wav, mix_pcm)
        proc = subprocess.Popen(
            [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
             "-i", "pipe:0", "-i", str(wav), "-c:v", "libx264", "-preset", preset, "-crf", "18", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-shortest",
             "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
        frames = int(math.ceil(total * FPS))
        for i in range(frames):
            proc.stdin.write(renderer.blurred(i / FPS, blur))
            if i % FPS == 0:
                print(f"\r  rendering {i / frames:4.0%}", end="", file=sys.stderr, flush=True)
        proc.stdin.close()
        if proc.wait() != 0:
            sys.exit("ffmpeg failed")
        print("\r  rendering 100%", file=sys.stderr)


def review_sheets(video: Path, scenes, suf=""):
    d = video.parent
    sel = "+".join(f"eq(n\\,{int((sc.start + sc.speech * 0.92) * FPS)})" for sc in scenes)
    cols = min(len(scenes), 6); rows = math.ceil(len(scenes) / cols)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vf", f"select='{sel}',scale=270:-1,tile={cols}x{rows}",
                    "-frames:v", "1", "-vsync", "0", str(d / f"contact{suf}.png")], check=True)
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vf", "fps=1,scale=360:-1,tile=5x1",
                    "-frames:v", "1", str(d / f"phone{suf}.png")], check=True)


def srt_time(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path, scenes):
    out = []
    for i, s in enumerate(scenes, 1):
        e = s.start + s.word_times[-1][1] + 0.15
        out.append(f"{i}\n{srt_time(s.start + s.word_times[0][0])} --> {srt_time(e)}\n{s.text}\n")
    path.write_text("\n".join(out), encoding="utf-8")


def fmt_slug(f): return f.replace(":", "x")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", type=Path, help="script file (blank line between scenes)")
    ap.add_argument("--setup", action="store_true", help="download Whisper + offline voice now, then exit")
    ap.add_argument("--topic", help="let an LLM write the script (needs an API key), or combine with --points")
    ap.add_argument("--points", default="", help="semicolon-separated points; used by the LLM, or offline as the body")
    ap.add_argument("--meta", type=Path, help='JSON with "caption", "hashtags", "props" (one prop name or "" per scene), e.g. written by Claude Code')
    ap.add_argument("--cta", default=None, help="call to action text for the final scene")
    ap.add_argument("--tone", default="direct, warm, confident")
    ap.add_argument("--seconds", type=int, default=30, help="target length when generating a script")
    ap.add_argument("-o", "--out", type=Path, default=Path("out/reel.mp4"))
    ap.add_argument("--formats", default="9:16", help=f"comma list from {', '.join(FORMATS)}")
    ap.add_argument("--lang", default="en", help="voice/caption language code (en, es, fr, de, pt, it, ru, el, vi...)")
    ap.add_argument("--tts", choices=["auto", "edge", "piper", "elevenlabs", "openai", "file", "none"], default="auto",
                    help="auto = edge (3 tries) -> offline piper -> silent estimate")
    ap.add_argument("--voice", default=None, help="provider voice name/id (edge: see --list-voices)")
    ap.add_argument("--rate", default=None, help="edge speaking rate, e.g. +8%%")
    ap.add_argument("--pitch", default=None, help="edge pitch, e.g. -4Hz")
    ap.add_argument("--list-voices", nargs="?", const="en", metavar="LANG", help="list Edge voices with personality tags, then exit")
    ap.add_argument("--look", choices=list(looks.LOOKS), default=None,
                    help="style preset: captions, camera, cuts, grade, music mood and voice (default: brief, else hype)")
    ap.add_argument("--audio", type=Path, help="your own voiceover (with --tts file); aligned to the script by Whisper")
    ap.add_argument("--mood", choices=list(music.MOODS), default=None)
    ap.add_argument("--bpm", type=float, default=None, help="beat grid (default: the mood's tempo)")
    ap.add_argument("--music", choices=["synth", "none"], default="synth")
    ap.add_argument("--music-file", type=Path, help="your own (royalty-free) track; cuts land on its detected beats")
    ap.add_argument("--music-start", type=float, default=None, help="seconds into the music to start from")
    ap.add_argument("--music-search", default=None, help="find a CC0 / CC BY track on Wikimedia Commons, e.g. 'upbeat funk'")
    ap.add_argument("--style", choices=["auto", "footage", "cards"], default="auto",
                    help="footage = full-screen b-roll + kinetic captions; cards = animated typographic cards. "
                         "auto picks footage when clips are available")
    ap.add_argument("--broll-dir", type=Path, help="folder of your own video clips for the footage style")
    ap.add_argument("--title", default=None, help="short series title shown at the top (footage style)")
    ap.add_argument("--accent", choices=list(ACCENTS), default=None, help="caption highlight colour (footage style)")
    ap.add_argument("--no-polish", action="store_true", help="skip the voice EQ/compression chain")
    ap.add_argument("--palette", choices=PALETTES, default="studio")
    ap.add_argument("--host", choices=["auto", "paper", "none"], default="auto",
                    help="lip-synced paper-cut presenter (cards style; auto = on for cards)")
    ap.add_argument("--host-photo", type=Path, help="use this photo as the host's face (square-cropped)")
    ap.add_argument("--no-props", action="store_true", help="disable script-matched illustrations")
    ap.add_argument("--handle", default="", help="e.g. @yourname; shown on every scene and the end screen")
    ap.add_argument("--font", default=None, help="bold .ttf path (required for CJK/Arabic/Hebrew/Thai)")
    ap.add_argument("--blur", type=int, default=3, help="sub-frames per frame for motion blur (1 = off, faster)")
    ap.add_argument("--max-scene-words", type=int, default=14)
    ap.add_argument("--wpm", type=int, default=165, help="speaking rate for --tts none")
    ap.add_argument("--hashtags", nargs="*", default=None)
    ap.add_argument("--max-seconds", type=float, default=90)
    ap.add_argument("--history", type=Path, default=Path(".reel_history.json"), help="log of past scripts for the originality gate")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--force", action="store_true", help="render even if quality gates fail")
    a = ap.parse_args()
    load_env(ROOT / ".env")
    if a.list_voices:
        voice.list_voices(a.list_voices); return
    if a.setup:
        voice.setup([a.lang]); return
    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    for f in formats:
        if f not in FORMATS: ap.error(f"unknown format {f}; choose from {', '.join(FORMATS)}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    meta = json.loads(a.meta.read_text(encoding="utf-8")) if a.meta else {}
    # settings: command line > brief (meta) > look preset
    look = looks.resolve(a.look or meta.get("look") or "hype", meta.get("look_overrides"))
    pick = lambda cli, key: cli if cli is not None else (meta.get(key) if meta.get(key) not in (None, "") else look.get(key))
    a.voice, a.rate, a.pitch = pick(a.voice, "voice"), pick(a.rate, "rate"), pick(a.pitch, "pitch")
    a.mood, a.accent = pick(a.mood, "mood"), pick(a.accent, "accent")
    if a.mood not in music.MOODS: a.mood = "upbeat"
    a.music_search = a.music_search or meta.get("music_search")
    if not a.music_file and meta.get("music_file"): a.music_file = Path(meta["music_file"])
    if a.music_start is None: a.music_start = float(meta.get("music_start") or 0.0)
    if a.lang != "en" and a.voice and a.voice.startswith("en-") and not a.voice.endswith("MultilingualNeural"):
        a.voice = ""          # an English-only voice can't read another language; use the language default

    # 1. script
    log("1/6 script")
    if a.topic:
        pts = [p for p in a.points.split(";") if p.strip()]
        meta = {**meta, **scriptmod.generate(a.topic, pts, seconds=a.seconds, tone=a.tone, cta=a.cta)}
        raw = "\n\n".join(meta["scenes"])
        (a.out.parent / "script.txt").write_text(raw + "\n", encoding="utf-8")
    elif a.script:
        raw = a.script.read_text(encoding="utf-8")
    else:
        ap.error("give a script file or --topic")
    scenes = scriptmod.parse_script(raw, a.max_scene_words)
    if len(scenes) < 2: sys.exit("need at least 2 scenes")
    props = meta.get("props")
    figures.assign_props(scenes, props if props and len(props) == len(scenes) else None)
    broll = meta.get("broll") or []
    if broll and len(broll) != len(scenes):
        log(f"    ! meta has {len(broll)} b-roll queries for {len(scenes)} scenes; using them in order")
    for s_, q in zip(scenes, broll):
        s_.broll = q or None
    pexels_key = os.environ.get("PEXELS_API_KEY", "").strip()
    has_paths = any(s_.broll and Path(s_.broll).exists() for s_ in scenes)
    style = a.style
    if style == "auto":
        style = "footage" if (pexels_key or a.broll_dir or has_paths) else "cards"
        if style == "cards":
            log("    style: cards (for the footage style add a free PEXELS_API_KEY to .env, or pass --broll-dir)")
    if style == "footage" and not (pexels_key or a.broll_dir or has_paths):
        sys.exit("footage style needs PEXELS_API_KEY (in .env), --broll-dir, or clip paths in the meta 'broll' list")
    log(f"    style: {style}, look: {a.look or meta.get('look') or 'hype'}, voice: {a.voice or 'default'} {a.rate} {a.pitch}, "
        f"mood: {a.mood}")
    log("    " + ", ".join(f"{s.kind}" + (f"+{s.prop}" if s.prop else "") for s in scenes))

    # 2. voice
    log(f"2/6 voice ({a.tts})")
    voice.synthesize(scenes, a.tts, a.voice or "", a.lang, a.wpm, a.rate, a.audio, a.pitch)

    # 3. timing
    track, track_start, music_credit = None, 0.0, ""
    if a.music_search and not a.music_file:
        try:
            path, msg = musicsearch.find_track(a.music_search)
        except Exception as e:
            path, msg = None, f"music search failed: {e}"
        if path:
            a.music_file, music_credit = path, msg
            log(f"    {msg}")
        else:
            log(f"    ! {msg}; using the synthesized '{a.mood}' bed")
    if a.music_file:
        track = music.load_track(a.music_file)
        tb, phase, conf = music.detect_beats(track[int(a.music_start * music.SR):])
        track_start = a.music_start + phase
        log(f"    music file: {tb:.1f} bpm, first beat at {track_start:.2f}s, beat confidence {conf:.0%}")
        if conf < 0.3:
            log("    ! this track has no clear beat; cuts will follow the voice, not the music (pass --bpm to force a grid)")
            tb, track_start = 120.0, a.music_start
    bpm = a.bpm or (tb if track is not None else music.mood_bpm(a.mood))
    total = compute_timing(scenes, bpm)
    log(f"3/6 timing: {total:.1f}s @ {bpm:.0f} bpm, captions from: {scenes[0].timing_source}")
    voice_pcm = np.concatenate([s.audio for s in scenes])

    # 4. gates (every requested format has its own layout, so each is checked)
    renderers, all_hard, gates_out = {}, [], {}
    history = load_history(a.history)
    credits = {}
    title_text = a.title if a.title is not None else meta.get("title", "")
    for f in formats:
        r = None
        if style == "footage":
            log(f"    finding footage for {f}")
            clips = footage.find_clips(scenes, FORMATS[f], pexels_key or None, a.broll_dir)
            if any(clips):
                r = FootageRenderer(scenes, clips, FORMATS[f], a.handle, title_text, a.accent, a.font, look)
                r.clip_names = [c.source_id for c in clips]
                for c in clips:
                    if c: credits[c.credit] = 1
            else:
                log(f"    ! no footage found for {f}; falling back to cards")
        if r is None:
            host = "paper" if a.host == "auto" else a.host
            r = Renderer(scenes, a.palette, a.handle, a.font, FORMATS[f], host, not a.no_props, a.host_photo, voice_pcm)
        renderers[f] = r
        g = run_gates(scenes, r, total, a.max_seconds)
        target = meta.get("duration")
        if target and abs(total - float(target)) > max(4.0, 0.25 * float(target)):
            g["warnings"].append(f"reel is {total:.0f}s but the brief targets {float(target):.0f}s; "
                                 f"{'cut' if total > float(target) else 'add'} a scene")
        names = getattr(r, "clip_names", None)
        if names:
            g["info"]["footage"] = names
            reused = [i + 1 for i in range(1, len(names)) if names[i] in names[:i]]
            if reused:
                g["warnings"].append(f"scenes {', '.join(map(str, reused))} reuse a clip already shown; give them their own b-roll query")
            missing = [i + 1 for i, s_ in enumerate(scenes) if not s_.broll]
            if missing and pexels_key and not a.broll_dir:
                g["warnings"].append(f"scenes {', '.join(map(str, missing))} had no b-roll query; footage was guessed from the words")
        gates_out[f] = g
        all_hard += [f"[{f}] {m}" for m in g["hard_failures"]]
    title = a.topic or (a.script.name if a.script else "")
    oh, ow, oi = originality(scenes, history, title)
    all_hard += oh
    for g in gates_out.values():
        g["hard_failures"] += oh; g["warnings"] += ow; g["info"].update(oi); g["passed"] = not g["hard_failures"]
    first = gates_out[formats[0]]
    (a.out.parent / "gates.json").write_text(json.dumps(gates_out if len(formats) > 1 else first, indent=2))
    log("4/6 quality gates: " + ("PASS" if not all_hard else "FAIL"))
    for m in dict.fromkeys(all_hard): log(f"    ✗ {m}")
    for m in dict.fromkeys(w for g in gates_out.values() for w in g["warnings"]): log(f"    ! {m}")
    if all_hard and not a.force:
        sys.exit("fix the above (or use --force)")

    # 5. render
    mix = music.mix(voice_pcm, scenes, a.mood, bpm, a.music == "synth", raw, track, track_start, not a.no_polish)
    outs = {}
    for f in formats:
        out = a.out if len(formats) == 1 else a.out.with_name(f"{a.out.stem}_{fmt_slug(f)}{a.out.suffix}")
        log(f"5/6 render {f} → {out.name}")
        render_video(scenes, renderers[f], out, total, mix, a.blur, "veryfast" if a.blur <= 1 else "medium")
        outs[f] = out

    # 6. extras
    log("6/6 posters, review sheets, caption, subtitles")
    d = a.out.parent
    for f, out in outs.items():
        suf = "" if len(formats) == 1 else f"_{fmt_slug(f)}"
        renderers[f].frame(min(scenes[0].word_times[-1][1] + 0.1, scenes[0].dur - 0.05)).save(d / f"poster{suf}.png")
        review_sheets(out, scenes, suf)
    write_srt(a.out.with_suffix(".srt"), scenes)
    tags = a.hashtags if a.hashtags is not None else meta.get("hashtags") or ["reels"]
    tagline = " ".join("#" + t.lstrip("#") for t in tags)
    cap = meta.get("caption") or f"{scenes[0].text}\n\n{scenes[-1].text}"
    if music_credit:
        cap += f"\n\n{music_credit.split(', via')[0]}"
    (d / "caption.txt").write_text(f"{cap}\n\n{tagline}\n", encoding="utf-8")
    (d / "timing.json").write_text(json.dumps(
        [{"text": s.text, "kind": s.kind, "prop": s.prop, "broll": s.broll, "emph": sorted(s.emph), "start": round(s.start, 2), "dur": round(s.dur, 2),
          "words": [[w, round(s.start + x, 2), round(s.start + y, 2)] for w, (x, y) in zip(s.words, s.word_times)]}
         for s in scenes], indent=1))
    if credits or music_credit:
        txt = ("Footage:\n" + "\n".join(f"- {c}" for c in credits) + "\n") if credits else ""
        txt += f"\n{music_credit}\n" if music_credit else ""
        (d / "credits.txt").write_text(txt, encoding="utf-8")
    for r in renderers.values():
        if hasattr(r, "close"): r.close()
    if not a.no_history:
        save_history(a.history, scenes, title)
    log("done → " + ", ".join(str(o) for o in outs.values()))


if __name__ == "__main__":
    main()
