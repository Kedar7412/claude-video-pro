"""Mixed-engine videos: render each segment with the engine that suits it, then stitch them into one video.

    python run.py mix plan.json [--reuse] [--only 2,3]

Engines (one per segment):
  reel         this repo's pipeline      {"engine": "reel", "script": "scripts/x.txt", "meta": "scripts/x.json", "args": []}
  animate      procedural canvas styles  {"engine": "animate", "piece": "pieces/x"}           (~/.claude/skills/animate)
  remotion     React compositions        {"engine": "remotion", "project": "remotion", "comp": "Intro", "props": {...}}
  hyperframes  HTML compositions         {"engine": "hyperframes", "project": "hyperframes"}
  file         an existing clip          {"engine": "file", "src": "out/x/reel.mp4"}
Every segment can also take "take": [start, end] (seconds of its render to keep) and "transition": {"type": "fade",
"d": 0.3} into it (any ffmpeg xfade type; "cut" or d 0 = hard cut).

Audio: by default each segment keeps its own sound (silence if it has none). With "audio": {"voice": "v.wav",
"music": "m.mp3", "music_db": -16} the segments are muted and one continuous voice + music track runs under the
whole video (music ducked under the voice): use that when one narrator speaks across engine changes.
Output: plan "out" (default out/<plan name>/mix.mp4), H.264 yuv420p, -14 LUFS, plus contact.png (one frame per segment)
and segments/ (each normalised segment, reused with --reuse).
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANIMATE = Path.home() / ".claude" / "skills" / "animate"


def log(msg): print(msg, file=sys.stderr, flush=True)


def run(cmd, cwd=None):
    log("  $ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=cwd)
    if r.returncode:
        sys.exit(f"command failed ({r.returncode}): {cmd[0]}")


def tool(name):
    p = shutil.which(name) or shutil.which(name + ".cmd")
    if not p:
        sys.exit(f"{name} not found on PATH")
    return p


def probe(path):
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    j = json.loads(out)
    return float(j["format"]["duration"]), any(s["codec_type"] == "audio" for s in j.get("streams", []))


# ---- engines: each renders one segment to raw_path
def render_reel(s, raw):
    args = [s["script"]] + (["--meta", s["meta"]] if s.get("meta") else []) + s.get("args", []) + ["-o", raw]
    run([sys.executable, ROOT / "reel.py", *args], cwd=ROOT)


def render_animate(s, raw):
    piece = ROOT / s["piece"]
    run(["node", ANIMATE / "tools" / "build.mjs", piece])
    run(["node", ANIMATE / "tools" / "export.mjs", piece, *s.get("args", [])])
    shutil.copy(piece / "renders" / "final.mp4", raw)


def render_remotion(s, raw):
    proj = ROOT / s.get("project", "remotion")
    cmd = [tool("npx"), "remotion", "render", s["comp"], raw]
    if s.get("props"):
        pf = raw.with_suffix(".props.json")
        pf.write_text(json.dumps(s["props"]), encoding="utf-8")
        cmd.append(f"--props={pf}")
    run(cmd + s.get("args", []), cwd=proj)


def render_hyperframes(s, raw):
    proj = ROOT / s.get("project", "hyperframes")
    # the project's package is itself named "hyperframes", so pin the CLI by version to avoid resolving the folder
    run([tool("npx"), "--yes", f"hyperframes@{s.get('version', 'latest')}", "render", "-o", raw, *s.get("args", [])], cwd=proj)


def render_file(s, raw):
    shutil.copy(ROOT / s["src"], raw)


ENGINES = {"reel": render_reel, "animate": render_animate, "remotion": render_remotion,
           "hyperframes": render_hyperframes, "file": render_file}


def normalise(raw, seg, s, W, H, fps):
    """Trim, cover-crop to WxH, fixed fps, yuv420p; 48 kHz stereo audio (silence when the render has none)."""
    dur, has_audio = probe(raw)
    a, b = s.get("take", [0, dur])
    b = min(b, dur)
    length = b - a
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},setsar=1,format=yuv420p"
    cmd = [tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{length:.3f}", "-i", raw]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-map", "0:v", "-map", "0:a" if has_audio else "1:a", "-vf", vf,
            "-af", f"aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{length:.3f}",
            "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-c:a", "pcm_s16le", "-t", f"{length:.3f}", seg]
    run(cmd)
    return length


def stitch(segs, lengths, plan, out):
    """Join the segments: xfade / acrossfade where a transition is asked for, a hard cut otherwise."""
    cmd, fc = [tool("ffmpeg"), "-y", "-v", "error"], []
    for i, p in enumerate(segs):
        cmd += ["-i", p]
        fc.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[s{i}]")   # one timebase, or xfade refuses after a concat
    v, a, acc = "[s0]", "[0:a]", lengths[0]
    for i in range(1, len(segs)):
        tr = plan["segments"][i].get("transition") or {}
        d = 0 if tr.get("type", "cut") == "cut" else float(tr.get("d", 0.3))
        nv, na = f"[v{i}]", f"[a{i}]"
        if d > 0:
            fc.append(f"{v}[s{i}]xfade=transition={tr['type']}:duration={d}:offset={acc - d:.3f},settb=AVTB{nv}")
            fc.append(f"{a}[{i}:a]acrossfade=d={d}{na}")
            acc += lengths[i] - d
        else:
            fc.append(f"{v}{a}[s{i}][{i}:a]concat=n=2:v=1:a=1{nv}{na}")
            acc += lengths[i]
        v, a = nv, na
    au = plan.get("audio") or {}
    if au.get("voice") or au.get("music"):
        k = len(segs)
        vo = mu = None
        if au.get("voice"):
            cmd += ["-i", ROOT / au["voice"]]; vo = f"[{k}:a]"; k += 1
        if au.get("music"):
            cmd += ["-stream_loop", "-1", "-i", ROOT / au["music"]]; mu = f"[{k}:a]"; k += 1
        fc.append(f"{a}anullsink")
        if vo and mu:
            fc.append(f"{vo}aresample=48000,aformat=channel_layouts=stereo,asplit[vo][sc]")
            fc.append(f"{mu}aresample=48000,aformat=channel_layouts=stereo,volume={au.get('music_db', -16)}dB[mu]")
            fc.append("[mu][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=300[duck]")
            fc.append("[vo][duck]amix=inputs=2:normalize=0[mix]")
        else:
            fc.append(f"{vo or mu}aresample=48000,aformat=channel_layouts=stereo[mix]")
        a = "[mix]"
    fc.append(f"{a}apad,atrim=0:{acc:.3f},loudnorm=I=-14:TP=-1:LRA=11[aout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", v, "-map", "[aout]", "-c:v", "libx264", "-crf", "18",
            "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(plan.get("fps", 30)), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{acc:.3f}", out]
    run(cmd)
    return acc


def contact(segs, lengths, path, W, H):
    """One frame from the middle of each segment, side by side, labelled by engine order."""
    cmd, fc = [tool("ffmpeg"), "-y", "-v", "error"], []
    for i, (p, L) in enumerate(zip(segs, lengths)):
        cmd += ["-ss", f"{L / 2:.3f}", "-i", p]
        fc.append(f"[{i}:v]trim=end_frame=1,scale={W // 4}:{H // 4}[c{i}]")
    fc.append("".join(f"[c{i}]" for i in range(len(segs))) + f"hstack=inputs={len(segs)}[o]" if len(segs) > 1 else "[c0]null[o]")
    run(cmd + ["-filter_complex", ";".join(fc), "-map", "[o]", "-frames:v", "1", path])


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        sys.exit(__doc__)
    plan_path = Path(args[0])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    reuse = "--reuse" in args
    only = {int(x) for x in args[args.index("--only") + 1].split(",")} if "--only" in args else None
    W, H = plan.get("size", [1080, 1920])
    fps = plan.get("fps", 30)
    out = ROOT / plan.get("out", f"out/{plan_path.stem}/mix.mp4")
    sdir = out.parent / "segments"
    sdir.mkdir(parents=True, exist_ok=True)
    segs, lengths = [], []
    for i, s in enumerate(plan["segments"], 1):
        eng = s["engine"]
        if eng not in ENGINES:
            sys.exit(f"segment {i}: unknown engine {eng!r} (use {', '.join(ENGINES)})")
        raw, seg = sdir / f"{i:02d}-{eng}.raw.mp4", sdir / f"{i:02d}-{eng}.mp4"
        if not (reuse and raw.exists()) and (only is None or i in only or not raw.exists()):
            log(f"[{i}/{len(plan['segments'])}] rendering with {eng}")
            ENGINES[eng](s, raw)
        lengths.append(normalise(raw, seg, s, W, H, fps))
        segs.append(seg)
    total = stitch(segs, lengths, plan, out)
    contact(segs, lengths, out.with_name("contact.png"), W, H)
    report = {"out": out.relative_to(ROOT).as_posix(), "duration": round(total, 2),
              "segments": [{"n": i + 1, "engine": s["engine"], "seconds": round(L, 2)} for i, (s, L) in enumerate(zip(plan["segments"], lengths))]}
    out.with_name("mix.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    log(f"wrote {out} ({total:.1f}s from {len(segs)} segments: {' > '.join(s['engine'] for s in plan['segments'])})")
