"""Long-form engine (minutes to hours): chapters, narration, music, footage + stills, burned-in captions, YouTube package.

Everything visual is composed by ffmpeg, one short shot per call (captions are burned with libass), so a 2-hour video
renders in tens of minutes instead of hours. Work is resumable: finished voice blocks, clips and shots are reused.

Pipeline: parse -> narration (parallel, cached) -> timeline -> captions (ASS, word-by-word fill) -> footage pools ->
shot plan -> render shots (parallel, resumable) -> concat -> audio (music + ducking + loudness) -> mux -> extras.
"""
import argparse, bisect, concurrent.futures as cf, hashlib, json, math, os, re, shutil, subprocess, sys, time, wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from . import footage, images, looks, music, musicsearch, voice
from .common import FFMPEG, SR
from .kinetic import ACCENTS, FONTS, FONT_FILES
from .longscript import parse

ROOT = Path(__file__).resolve().parent.parent
INTRO, SENT_GAP, PARA_GAP, CH_GAP = 2.5, 0.14, 0.50, 0.90
PRESETS = {"fast": ("superfast", 24), "balanced": ("veryfast", 23), "best": ("faster", 21)}
MOTIONS = ["zoomin", "panr", "zoomout", "panl", "zoomin", "panu", "panr", "zoomout"]
SIZES = {720: (1280, 720), 1080: (1920, 1080)}


def log(msg): print(msg, file=sys.stderr, flush=True)


# ───────────────────────── progress ─────────────────────────
class Progress:
    def __init__(self, path):
        self.path, self.t0, self.data = Path(path), time.time(), {}

    def update(self, stage, done=0, total=0, msg="", eta=None, finished=False, error=None):
        self.data = {"stage": stage, "done": done, "total": total, "pct": round(100 * done / total) if total else 0,
                     "eta_min": None if eta is None else round(eta / 60, 1), "message": msg,
                     "elapsed_min": round((time.time() - self.t0) / 60, 1), "finished": finished, "error": error,
                     "updated": time.strftime("%H:%M:%S"), "pid": os.getpid()}
        try: self.path.write_text(json.dumps(self.data))
        except OSError: pass


# ───────────────────────── ASS captions ─────────────────────────
def ass_color(rgb, alpha=0):
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ass_time(t):
    cs = max(0, int(round(t * 100)))
    h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def esc(s): return s.replace("\\", "").replace("{", "(").replace("}", ")")


FONT_NAMES = {"anton": ("Anton", 0, 0.074), "montserrat": ("Montserrat", 1, 0.054), "playfair": ("Playfair Display", 0, 0.060)}


def ass_header(W, H, look, accent):
    cap = look["caption"]
    fam = cap.get("font", "anton")
    name, bold, frac = FONT_NAMES.get(fam, FONT_NAMES["montserrat"])
    size = int(H * frac * min(1.15, max(1.0, cap.get("size", 1.0))))   # long-form is read on phones and TVs: never below base
    outline = max(2, round(H * 0.0055)) if cap.get("stroke", True) else 0
    shadow = 0 if cap.get("stroke", True) else max(2, round(H * 0.0025))
    mv, mh = int(H * 0.085), int(W * 0.08)
    acc, white = ass_color(accent), ass_color((255, 255, 255))
    def style(n, f, b, sz, prim, sec, ol, sh, al, mvv, spacing=0):
        return (f"Style: {n},{f},{sz},{prim},{sec},{ass_color((0, 0, 0))},{ass_color((0, 0, 0), 0x80)},{b},0,0,0,100,100,"
                f"{spacing},0,1,{ol},{sh},{al},{mh},{mh},{mvv},1")
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style("Cap", name, bold, size, acc, white, outline, shadow, 2, mv),
        style("ChLabel", "Montserrat", 1, int(H * 0.044), acc, acc, 0, 3, 5, 0, spacing=8),
        style("ChTitle", name, bold, int(H * 0.098), white, white, outline, shadow + 1, 5, 0),
        style("Fact", "Anton", 0, int(H * 0.15), acc, acc, max(4, outline), 3, 5, 0),
        style("Box", "Montserrat", 0, 20, white, white, 0, 0, 7, 0), "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    return "\n".join(lines) + "\n"


def make_lines(block, upper):
    """Caption lines (<= 2 rows) for one narration block, with word-by-word fill timing, in absolute seconds."""
    ws, wt, base = block.words, block.word_times, block.start
    groups, cur, chars = [], [], 0
    for i, w in enumerate(ws):
        cur.append(i); chars += len(w) + 1
        if (w[-1:] in ".!?…" and chars >= 18) or chars >= 58 or (w[-1:] in ",;:—" and chars >= 34) or len(cur) >= 14:
            groups.append(cur); cur, chars = [], 0
    if cur:
        if groups and len(cur) < 3: groups[-1] += cur
        else: groups.append(cur)
    out = []
    for g in groups:
        first, last = wt[g[0]][0] + base, wt[g[-1]][1] + base
        parts = []
        for j, i in enumerate(g):
            nxt = wt[g[j + 1]][0] if j + 1 < len(g) else wt[i][1]
            d = max(1, int(round((nxt - wt[i][0]) * 100)))
            w = esc(ws[i].upper() if upper else ws[i])
            parts.append(f"{{\\kf{d}}}{w}")
        total = sum(len(ws[i]) for i in g) + len(g) - 1
        if total > 30 and len(g) > 1:
            best = min(range(1, len(g)), key=lambda k: abs(sum(len(ws[i]) + 1 for i in g[:k]) - sum(len(ws[i]) + 1 for i in g[k:])))
            text = " ".join(parts[:best]) + "\\N" + " ".join(parts[best:])
        else:
            text = " ".join(parts)
        out.append({"t0": first - 0.05, "t1": last + 0.30, "text": "{\\k5}" + text, "style": "Cap", "layer": 1,
                    "plain": " ".join(ws[i] for i in g), "first": first, "last": last})
    return out


def box_event(W, H, t0, t1, alpha, fade=(300, 450)):
    return {"t0": t0, "t1": t1, "style": "Box", "layer": 0,
            "text": f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&\\1a&H{alpha:02X}&\\fad({fade[0]},{fade[1]})\\p1}}"
                    f"m 0 0 l {W} 0 l {W} {H} l 0 {H}"}


def chapter_events(W, H, ci, ch, upper):
    ev = [box_event(W, H, ch.start, ch.start + INTRO, 0x70)]
    t = ch.title.upper() if upper else ch.title
    if len(t) > 26 and " " in t:
        k = min((m.start() for m in re.finditer(" ", t)), key=lambda p: abs(p - len(t) / 2))
        t = esc(t[:k]) + "\\N" + esc(t[k + 1:])
    else:
        t = esc(t)
    ev.append({"t0": ch.start + 0.1, "t1": ch.start + INTRO, "style": "ChLabel", "layer": 2,
               "text": f"{{\\an5\\pos({W // 2},{int(H * 0.40)})\\fad(350,450)}}CHAPTER {ci + 1:02d}"})
    ev.append({"t0": ch.start + 0.1, "t1": ch.start + INTRO, "style": "ChTitle", "layer": 2,
               "text": f"{{\\an5\\pos({W // 2},{int(H * 0.51)})\\fad(450,450)}}{t}"})
    return ev


def fact_events(W, H, b, upper):
    t = b.fact.upper()
    if len(t) > 18 and " " in t:
        k = min((m.start() for m in re.finditer(" ", t)), key=lambda p: abs(p - len(t) / 2))
        t = esc(t[:k]) + "\\N" + esc(t[k + 1:])
    else:
        t = esc(t)
    t0, t1 = b.start, b.start + 4.2
    return [box_event(W, H, t0, t1, 0x78, (250, 350)),
            {"t0": t0, "t1": t1, "style": "Fact", "layer": 2, "text": f"{{\\an5\\pos({W // 2},{H // 2})\\fad(250,350)}}{t}"}]


def shot_ass(header, events, T0, T1):
    rows = []
    for e in events:
        if e["t1"] <= T0 or e["t0"] >= T1:
            continue
        a, b = max(e["t0"], T0) - T0, min(e["t1"], T1) - T0
        rows.append(f"Dialogue: {e['layer']},{ass_time(a)},{ass_time(b)},{e['style']},,0,0,0,,{e['text']}")
    return header + "\n".join(rows) + "\n"


# ───────────────────────── timeline ─────────────────────────
def build_timeline(proj):
    t = 0.0
    for ci, ch in enumerate(proj.chapters):
        ch.start = t
        if ch.card: t += INTRO
        for b in ch.blocks:
            b.start = t
            b.dur = len(b.audio) / SR
            t += b.dur + (PARA_GAP if b.para_end else SENT_GAP)
        t += CH_GAP
        ch.end = t
    return t


def write_voice(proj, path, total_s):
    pos = 0
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        def pad_to(n):
            nonlocal pos
            while pos < n:
                k = min(n - pos, SR * 30)
                w.writeframes(b"\x00\x00" * k); pos += k
        for b in proj.blocks:
            pad_to(int(round(b.start * SR)))
            w.writeframes(b.audio.tobytes()); pos += len(b.audio)
        pad_to(int(round(total_s * SR)))


# ───────────────────────── footage planning ─────────────────────────
def _retry_pexels(fn, tries=3):
    for k in range(tries):
        try:
            return fn()
        except Exception as e:
            if "429" in str(e) and k < tries - 1:
                log("    Pexels rate limit reached; waiting 60 s"); time.sleep(60); continue
            raise


def build_pools(proj, size, key, broll_dir, default_pool, per_query, limit_res):
    """chapter index -> list of Clip. Pexels per query, or a local folder."""
    pools, used = {}, set()
    local = []
    if broll_dir:
        d = Path(broll_dir)
        local = sorted(p for p in d.iterdir() if p.suffix.lower() in footage.VIDEO_EXT) if d.is_dir() else []
    for ci, ch in enumerate(proj.chapters):
        qs = ch.broll or default_pool or [re.sub(r"[^a-zA-Z ]", " ", ch.title)]
        pool = []
        if local:
            ranked = sorted(local, key=lambda p: (-len(set(re.findall(r"[a-z]+", " ".join(qs).lower())) & set(re.findall(r"[a-z]+", p.stem.lower()))),
                                                  (local.index(p) - ci * 3) % len(local)))
            pool = [footage.Clip(p, footage.probe_duration(p), f"local file {p.name}", str(p)) for p in ranked[:max(3, per_query * len(qs))]]
        elif key:
            for q in qs:
                for _ in range(per_query):
                    try:
                        c = _retry_pexels(lambda: footage.pexels_clip(q, size, key, used, 6.0))
                    except Exception as e:
                        log(f"    ! footage for '{q}' failed: {e}"); break
                    if not c: break
                    used.add(c.source_id); pool.append(c)
        pools[ci] = pool
    return pools


def forced_clip(query, size, key, broll_dir, used):
    if broll_dir:
        return None
    if not key:
        return None
    try:
        c = _retry_pexels(lambda: footage.pexels_clip(query, size, key, used, 6.0))
    except Exception as e:
        log(f"    ! footage for '{query}' failed: {e}"); return None
    if c: used.add(c.source_id)
    return c


def plan_shots(proj, lines, total_s, fps, shot_sec):
    """Shot boundaries sit just before caption lines (so no caption straddles a cut), chapter starts always cut."""
    cycle = [1.0, 0.75, 1.15, 0.85, 1.3, 0.9]
    shots, k = [], 0
    def new(t, ci):
        nonlocal k
        shots.append({"t0": t, "chapter": ci, "target": shot_sec * cycle[k % len(cycle)]}); k += 1
    new(0.0, 0)
    prev_end = 0.0
    for L in lines:
        cur = shots[-1]
        if L["chapter"] != cur["chapter"]:
            new(proj.chapters[L["chapter"]].start, L["chapter"])
        elif L["first"] - cur["t0"] >= cur["target"] and L["first"] - cur["t0"] >= 3.0:
            new(max(L["first"] - 0.12, prev_end + 0.02), L["chapter"])
        prev_end = L["last"]
    # snap to the frame grid so durations add up exactly to the audio
    for i, s in enumerate(shots):
        s["f0"] = int(round(s["t0"] * fps)) if i else 0
    for i, s in enumerate(shots):
        s["f1"] = shots[i + 1]["f0"] if i + 1 < len(shots) else int(math.ceil(total_s * fps))
        s["t0"], s["t1"] = s["f0"] / fps, s["f1"] / fps
    return [s for s in shots if s["f1"] > s["f0"]]


def prepare_still(src, W, H, work):
    """Compose a cutaway image once: sharp image centred over a blurred, darkened copy of itself."""
    dst = work / "stills" / (hashlib.sha1(f"{src}|{W}x{H}".encode()).hexdigest()[:14] + ".png")
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    bg = ImageOps.fit(im, (W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(7)).resize((W, H), Image.BILINEAR)
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    fg = ImageOps.contain(im, (int(W * 0.88), int(H * 0.82)), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(dst)
    return dst


def assign_sources(proj, shots, pools, imgs, forced, fps):
    last_clip, uses = None, {}
    per_chapter = {}
    for s in shots:
        ci = s["chapter"]; n = per_chapter.get(ci, 0); per_chapter[ci] = n + 1
        pool, im = pools.get(ci, []), imgs.get(ci, [])
        s["motion"] = MOTIONS[(len(per_chapter) * 3 + n + ci) % len(MOTIONS)]
        # footage forced by a `> shot:` directive on a block that starts inside this shot
        fk = next((forced[id(b)] for b in proj.chapters[ci].blocks if id(b) in forced and s["t0"] - 0.01 <= b.start < s["t1"]), None)
        if fk:
            s.update(kind="clip", clip=fk, ss=0.8); uses[fk.source_id] = uses.get(fk.source_id, 0) + 1; last_clip = fk.source_id
            continue
        if im and n % 4 == 3:
            a = im[(n // 4) % len(im)]
            s.update(kind="image", image=a[0], credit=a[1]); continue
        if pool:
            order = sorted(range(len(pool)), key=lambda j: (uses.get(pool[j].source_id, 0), j))
            j = next((j for j in order if pool[j].source_id != last_clip), order[0])
            c = pool[j]
            u = uses.get(c.source_id, 0)
            dur = s["t1"] - s["t0"]
            spare = max(0.0, c.duration - dur - 1.0)
            s.update(kind="clip", clip=c, ss=round(0.5 + (u * 7.3) % spare if spare > 0.5 else 0.0, 2))
            uses[c.source_id] = u + 1; last_clip = c.source_id
        else:
            s.update(kind="gradient")
    return shots


# ───────────────────────── shot rendering ─────────────────────────
def strip_vignette(f): return re.sub(r",?vignette=[^,]*", "", f).strip(",")


def shot_filter(s, W, H, fps, grade, cut, amount):
    D = max(0.1, (s["f1"] - s["f0"]) / fps)
    z = 0.05 + 0.07 * amount
    cover = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,crop={W}:{H}"
    m = s["motion"]
    if m in ("zoomin", "zoomout"):
        e = f"(1+{z:.3f}*t/{D:.3f})" if m == "zoomin" else f"(1+{z:.3f}*(1-t/{D:.3f}))"
        move = (f"scale=w='trunc({W}*{e}/2)*2':h='trunc({H}*{e}/2)*2':eval=frame:flags=bilinear,crop={W}:{H}")
        pre = cover
    else:
        PW, PH = int(math.ceil(W * (1 + z * 1.6) / 2)) * 2, int(math.ceil(H * (1 + z * 1.6) / 2)) * 2
        pre = f"scale={PW}:{PH}:force_original_aspect_ratio=increase:flags=bicubic,crop={PW}:{PH}"
        a, b = (0.12, 0.88) if m == "panr" else (0.88, 0.12)
        if m == "panu":
            move = f"crop={W}:{H}:x='(iw-ow)/2':y='(ih-oh)*(0.85-0.7*t/{D:.3f})'"
        else:
            move = f"crop={W}:{H}:x='(iw-ow)*({a}+({b}-{a})*t/{D:.3f})':y='(ih-oh)*0.5'"
    chain = [f"fps={fps}"]
    if s["kind"] == "clip": chain += [pre, move]
    elif s["kind"] == "image": chain += [move if m in ("zoomin", "zoomout") else f"scale={W}:{H}", ] if m in ("zoomin", "zoomout") else [f"scale={int(math.ceil(W * 1.06 / 2)) * 2}:{int(math.ceil(H * 1.06 / 2)) * 2}", f"crop={W}:{H}:x='(iw-ow)*(0.1+0.8*t/{D:.3f})':y='(ih-oh)/2'"]
    elif s["kind"] == "gradient": chain += [move if m in ("zoomin", "zoomout") else f"crop={W}:{H}"]
    if grade: chain.append(grade)
    if cut in ("dip", "fade"):
        chain += [f"fade=t=in:st=0:d=0.22", f"fade=t=out:st={max(0.0, D - 0.22):.3f}:d=0.22"]
    chain += ["ass=shot.ass:fontsdir=fonts", "format=yuv420p"]
    return ",".join(chain), D


def shot_command(s, W, H, fps, grade, cut, amount, preset, crf, threads, out, ass_name):
    vf, D = shot_filter(s, W, H, fps, grade, cut, amount)
    vf = vf.replace("shot.ass", ass_name)
    enc = ["-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-threads", str(threads), out]
    n = str(s["f1"] - s["f0"])
    base = [FFMPEG, "-v", "error", "-y"]
    if s["kind"] == "clip":
        return base + ["-stream_loop", "-1", "-ss", f"{s['ss']:.3f}", "-i", str(s["clip"].path), "-frames:v", n, "-vf", vf] + enc
    if s["kind"] == "image":
        return base + ["-loop", "1", "-framerate", str(fps), "-i", str(s["image"]), "-frames:v", n, "-vf", vf] + enc
    g0, g1 = s.get("g", ("0x16222e", "0x2e2216"))
    return base + ["-f", "lavfi", "-i", f"gradients=s={W}x{H}:c0={g0}:c1={g1}:speed=0.012:r={fps}:d={D + 1:.2f}",
                   "-frames:v", n, "-vf", vf] + enc


def render_shots(shots, work, header, events, W, H, fps, grade, cut, amount, preset, crf, jobs, threads, prog, lines_t):
    sd = work / "shots"; sd.mkdir(parents=True, exist_ok=True)
    fd = sd / "fonts"; fd.mkdir(exist_ok=True)
    for f in FONTS.glob("*.ttf"):
        if not (fd / f.name).exists(): shutil.copy(f, fd / f.name)
    for i, s in enumerate(shots):
        key = json.dumps([s["f0"], s["f1"], s["kind"], str(s.get("clip") and s["clip"].path), s.get("ss"), str(s.get("image")),
                          s["motion"], W, H, fps, preset, crf, grade, cut, round(amount, 2)]) + shot_ass(header, events, s["t0"], s["t1"])
        s["file"] = f"s{i:05d}_{hashlib.sha1(key.encode()).hexdigest()[:8]}.mp4"
        s["ass"] = f"s{i:05d}.ass"
    keep = {s["file"] for s in shots} | {s["ass"] for s in shots}
    for f in sd.iterdir():                                   # stale files from an earlier plan
        if f.is_file() and f.name not in keep and f.suffix in (".mp4", ".ass"): f.unlink()
    todo = [s for s in shots if not (sd / s["file"]).exists()]
    log(f"    {len(shots)} shots, {len(shots) - len(todo)} already done")
    done, t0, vid_done = [len(shots) - len(todo)], time.time(), [0.0]
    total_vid = sum((s["f1"] - s["f0"]) / fps for s in todo) or 1.0
    errors = []

    def work_one(s):
        (sd / s["ass"]).write_text(shot_ass(header, events, s["t0"], s["t1"]), encoding="utf-8")
        tmp = sd / ("part_" + s["file"])
        cmd = shot_command(s, W, H, fps, grade, cut, amount, preset, crf, threads, tmp.name, s["ass"])
        t_start = time.time()
        for attempt in range(2):
            p = subprocess.run(cmd, cwd=sd, capture_output=True, text=True, errors="replace")
            if p.returncode == 0 and tmp.exists(): break
        else:
            raise RuntimeError(f"shot {s['file']} failed: {p.stderr.strip()[-300:]}")
        os.replace(tmp, sd / s["file"])
        s["secs"] = time.time() - t_start
        return (s["f1"] - s["f0"]) / fps

    with cf.ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(work_one, s): s for s in todo}
        for fu in cf.as_completed(futs):
            try:
                vid_done[0] += fu.result()
            except Exception as e:
                errors.append(str(e)); log(f"    ! {e}")
            done[0] += 1
            rate = vid_done[0] / max(1e-6, time.time() - t0)
            eta = (total_vid - vid_done[0]) / rate if rate else None
            prog.update("render", done[0], len(shots), f"{rate:.1f}x realtime", eta)
            if done[0] % 10 == 0 or done[0] == len(shots):
                log(f"    shots {done[0]}/{len(shots)}  {rate:.1f}x realtime  ETA {eta / 60 if eta else 0:.1f} min")
    by = {}
    for s in todo:
        if "secs" in s: by.setdefault(f"{s['kind']}/{s['motion']}", []).append(s["secs"] / ((s["f1"] - s["f0"]) / fps))
    if by:
        log("    render cost (seconds of CPU-job time per second of video): " +
            ", ".join(f"{k} {sum(v) / len(v):.1f}" for k, v in sorted(by.items())))
    if errors:
        raise SystemExit(f"{len(errors)} shot(s) failed; run again to retry only those. First error: {errors[0]}")
    return sd


# ───────────────────────── audio ─────────────────────────
def build_music_bed(path, total_s, tracks, mood, seed):
    """Mono wav covering total_s: the given tracks in order (looping, 3 s crossfades) or a looped synthesized bed."""
    xf = int(3 * SR)
    pos = 0
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        target = int(total_s * SR) + SR
        seq = []
        if tracks:
            for p in tracks:
                try:
                    x = music.load_track(p)
                    if len(x) > xf * 3: seq.append(x)
                except Exception as e:
                    log(f"    ! could not read track {p}: {e}")
        if not seq:
            bar = 60.0 / music.mood_bpm(mood) * 4
            n = int(round(60 / bar)) * bar                   # a whole number of bars so the loop is seamless
            seq = [music.build_music(int(n * SR), mood, music.mood_bpm(mood), seed).astype(np.float32)]
            peak = np.max(np.abs(seq[0])) or 1.0
            seq[0] = seq[0] / peak
        tail, i = None, 0
        while pos < target:
            x = seq[i % len(seq)]; i += 1
            if tail is not None:
                fade = np.linspace(0, 1, xf, dtype=np.float32)
                head = tail * (1 - fade) + x[:xf] * fade
                body = x[xf:-xf] if len(x) > 2 * xf else x[xf:]
                chunk = np.concatenate([head, body])
            else:
                chunk = x[:-xf] if len(x) > 2 * xf else x
            tail = x[-xf:] if len(x) > 2 * xf else None
            w.writeframes((np.clip(chunk, -1, 1) * 30000).astype(np.int16).tobytes())
            pos += len(chunk)


def mix_audio(voice_wav, bed_wav, out_m4a, music_gain=0.5):
    voice_chain = ("highpass=f=85,equalizer=f=250:t=q:w=1.0:g=-2.5,equalizer=f=3200:t=q:w=1.2:g=3,"
                   "equalizer=f=9000:t=q:w=1.0:g=1.5,acompressor=threshold=-21dB:ratio=3:attack=6:release=90:makeup=3")
    if bed_wav:
        fc = (f"[0:a]{voice_chain},asplit=2[v1][v2];[1:a]volume={music_gain}[m];"
              f"[m][v1]sidechaincompress=threshold=0.012:ratio=10:attack=20:release=450[d];"
              f"[v2][d]amix=inputs=2:duration=first:normalize=0[mix];[mix]loudnorm=I=-14:TP=-1.5:LRA=9[out]")
        cmd = [FFMPEG, "-v", "error", "-y", "-i", str(voice_wav), "-i", str(bed_wav), "-filter_complex", fc, "-map", "[out]"]
    else:
        cmd = [FFMPEG, "-v", "error", "-y", "-i", str(voice_wav), "-af", f"{voice_chain},loudnorm=I=-14:TP=-1.5:LRA=9"]
    subprocess.run(cmd + ["-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out_m4a)], check=True)


# ───────────────────────── extras ─────────────────────────
def hms(t):
    t = int(t); h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def make_thumbnail(path, bg_src, ss, text, accent, font_path=None):
    """bg_src: a source clip or image (not a rendered shot, which already has captions burned in)."""
    tmp = path.with_suffix(".bg.png")
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{ss:.2f}", "-i", str(bg_src), "-frames:v", "1", "-update", "1", str(tmp)])
    im = Image.open(tmp).convert("RGB").resize((1280, 720)) if tmp.exists() else Image.new("RGB", (1280, 720), (20, 20, 24))
    arr = np.asarray(im, dtype=np.float32)
    g = np.linspace(0.25, 0.85, 1280, dtype=np.float32)[None, :, None] if False else np.clip(1.1 - np.linspace(0, 1, 1280) * 1.0, 0.25, 1)[None, :, None]
    im = Image.fromarray((arr * np.clip(0.35 + 0.65 * (1 - np.linspace(0, 1, 1280)), 0.3, 1)[None, :, None]).astype(np.uint8))
    d = ImageDraw.Draw(im)
    fp = FONTS / FONT_FILES["anton"]
    words = text.upper().split()
    lines = [" ".join(words[:max(1, (len(words) + 1) // 2)]), " ".join(words[max(1, (len(words) + 1) // 2):])] if len(words) > 2 else [" ".join(words)]
    size = 190
    while size > 70:
        f = ImageFont.truetype(str(fp), size)
        if max(d.textlength(l, font=f) for l in lines if l) < 1280 * 0.62: break
        size -= 6
    y = 360 - len([l for l in lines if l]) * size * 0.58
    for i, l in enumerate([l for l in lines if l]):
        col = accent if i == len([l for l in lines if l]) - 1 else (255, 255, 255)
        d.text((70, y + i * size * 1.12), l, font=f, fill=col, stroke_width=max(6, size // 16), stroke_fill=(0, 0, 0))
    im.save(path, quality=92)
    tmp.unlink(missing_ok=True)


def srt_time(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ───────────────────────── gates ─────────────────────────
def long_gates(proj, shots, lines, total_s, fps, has_footage, meta, pools):
    hard, warn, info = [], [], {}
    words = proj.words
    minutes = total_s / 60
    info.update(duration_min=round(minutes, 1), chapters=len(proj.chapters), words=words, shots=len(shots))
    wpm = words / max(0.01, sum(b.speech for b in proj.blocks) / 60)
    info["narration_wpm"] = round(wpm)
    if not (115 <= wpm <= 200): warn.append(f"narration pace is {wpm:.0f} wpm (comfortable: 130-180)")
    if minutes > 8 and len(proj.chapters) < 3: warn.append("long video with fewer than 3 chapters; YouTube needs 3+ for chapter markers")
    for i, c in enumerate(proj.chapters):
        if c.end - c.start < 10 and i < len(proj.chapters) - 1: warn.append(f"chapter {i + 1} '{c.title}' is under 10 s; YouTube ignores chapters that short")
        if minutes > 10 and not c.sources: warn.append(f"chapter {i + 1} '{c.title}' lists no `> source:`; add the pages its facts come from")
        if minutes > 10 and not c.broll and not meta.get("broll"): warn.append(f"chapter {i + 1} '{c.title}' has no `> broll:` queries")
    lens = [(s["t1"] - s["t0"]) for s in shots]
    info["avg_shot_s"] = round(sum(lens) / len(lens), 1)
    if max(lens) > 14: warn.append(f"longest shot is {max(lens):.0f}s; viewers drift after ~10s without a change")
    clips = [s["clip"].source_id for s in shots if s["kind"] == "clip"]
    if clips:
        worst = max(clips.count(c) for c in set(clips))
        info["distinct_clips"] = len(set(clips))
        if worst > 5: warn.append(f"one clip is used {worst} times; add more `> broll:` queries to those chapters")
    elif not has_footage:
        warn.append("no footage was found; shots use plain gradients (add PEXELS_API_KEY, --broll-dir, or `> broll:` queries)")
    # pattern interrupts: something other than a plain clip (title card, fact card, image) at least every 3 minutes
    marks = sorted([c.start for c in proj.chapters if c.card] + [b.start for b in proj.blocks if b.fact] +
                   [s["t0"] for s in shots if s["kind"] == "image"])
    gaps = [b - a for a, b in zip([0.0] + marks, marks + [total_s])]
    info["longest_gap_without_card_min"] = round(max(gaps) / 60, 1)
    if minutes > 6 and max(gaps) > 180: warn.append(f"{max(gaps) / 60:.0f} minutes pass with no chapter card, fact card or image; add `> fact:` or `> images:`")
    # templated writing (YouTube 'inauthentic content': repetitive, templated, mass-produced)
    starts = [" ".join(b.words[:3]).lower() for b in proj.blocks if len(b.words) >= 5]
    if starts:
        top = max(set(starts), key=starts.count)
        share = starts.count(top) / len(starts)
        info["most_common_opening"] = f"'{top}' {share:.0%}"
        if share > 0.12 and starts.count(top) >= 4: warn.append(f"{share:.0%} of narration blocks start with '{top}'; vary the sentence openings")
    openers = ("in this chapter", "in this video", "let's dive", "let's explore", "without further ado", "welcome back", "hey guys")
    hits = [b.text[:40] for b in proj.blocks if b.text.lower().startswith(openers)]
    if hits: warn.append(f"{len(hits)} generic transition openers (e.g. '{hits[0]}...'); cut them or say something specific")
    if minutes > 10 and not meta.get("description"): warn.append("no `description` in the settings file; the YouTube package will only contain chapters and credits")
    if proj.words and not any(re.search(r"\d", b.text) for b in proj.blocks): warn.append("no numbers, dates or names in the narration; generic scripts blend in")
    return {"passed": not hard, "hard_failures": hard, "warnings": warn, "info": info}


# ───────────────────────── orchestration ─────────────────────────
def bench(W, H, fps, preset, crf, jobs, threads):
    """Seconds of video one parallel batch of shots renders per wall second on this machine."""
    d = 4.0
    cmd = lambda i: [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r={fps}:d={d}", "-vf", "format=yuv420p",
                     "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-threads", str(threads), "-f", "null", "-"]
    t0 = time.time()
    with cf.ThreadPoolExecutor(jobs) as ex:
        list(ex.map(lambda i: subprocess.run(cmd(i), check=True), range(jobs)))
    return 0.4 * jobs * d / (time.time() - t0)      # synthetic test pattern is ~2.5x cheaper than real footage + captions


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="long", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", type=Path, help="project script (see reelkit/longscript.py for the format)")
    ap.add_argument("--meta", type=Path, help="settings JSON: title, description, tags, look, voice, rate, pitch, accent, music_search, broll, thumb_text")
    ap.add_argument("-o", "--out", type=Path, help="output folder (default out/<script name>)")
    ap.add_argument("--res", type=int, choices=[720, 1080], default=1080)
    ap.add_argument("--fps", type=int, choices=[24, 25, 30], default=30)
    ap.add_argument("--quality", choices=list(PRESETS), default="balanced", help="encoder speed/size trade-off")
    ap.add_argument("--look", choices=list(looks.LOOKS), default=None)
    ap.add_argument("--tts", choices=["auto", "edge", "piper", "elevenlabs", "openai", "none"], default="auto")
    ap.add_argument("--voice", default=None); ap.add_argument("--rate", default=None); ap.add_argument("--pitch", default=None)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--workers", type=int, default=6, help="parallel narration requests")
    ap.add_argument("--jobs", type=int, default=0, help="parallel shot renders (default: half the CPU cores, max 4)")
    ap.add_argument("--shot-seconds", type=float, default=7.0, help="average shot length")
    ap.add_argument("--accent", default=None)
    ap.add_argument("--music-search", default=None); ap.add_argument("--music-file", type=Path, action="append")
    ap.add_argument("--music", choices=["on", "off"], default="on"); ap.add_argument("--music-volume", type=float, default=0.5)
    ap.add_argument("--broll-dir", type=Path); ap.add_argument("--clips-per-query", type=int, default=3)
    ap.add_argument("--max-clips", type=int, default=400, help="warn above this many downloaded clips")
    ap.add_argument("--limit-chapters", type=int, default=0, help="render only the first N chapters (for a quick preview)")
    ap.add_argument("--max-minutes", type=float, default=150)
    ap.add_argument("--plan-only", action="store_true", help="parse, estimate duration and render time, then stop")
    ap.add_argument("--detach", action="store_true", help="run in the background and return immediately")
    ap.add_argument("--status", type=Path, metavar="OUT_DIR", help="show progress of a background run")
    ap.add_argument("--force", action="store_true", help="render even if gates fail")
    ap.add_argument("--handle", default="")
    ap.add_argument("--assemble", type=Path, metavar="PROJECT_DIR",
                    help="join PROJECT_DIR/chapters/*.md (sorted) into PROJECT_DIR/script.md and print a progress table")
    ap.add_argument("--stop-after", choices=["plan", "audio"], help="diagnostic: stop before rendering video (plan) or after the audio mix (audio)")
    return ap, ap.parse_args(argv)


def status(out):
    p = Path(out) / "work" / "progress.json"
    if not p.exists():
        print("no progress file yet"); return
    d = json.loads(p.read_text())
    def alive(pid):
        try:
            if os.name == "nt":
                out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
                return str(pid) in out
            os.kill(pid, 0); return True
        except Exception:
            return False
    state = "FINISHED" if d.get("finished") else ("FAILED" if d.get("error") else "running")
    if state == "running" and not alive(d.get("pid", -1)):
        state = "STOPPED (process is gone; run the same command again to resume where it left off)"
    print(f"{state}: stage={d['stage']} {d['done']}/{d['total']} ({d['pct']}%)  {d['message']}  ETA {d['eta_min']} min  "
          f"elapsed {d['elapsed_min']} min  (updated {d['updated']})")
    if d.get("error"): print("error:", d["error"])
    lg = Path(out) / "render.log"
    if lg.exists():
        print("--- last log lines ---"); print("\n".join(lg.read_text(errors="replace").splitlines()[-8:]))


def assemble(pdir):
    """Chapters are written one file at a time (so a long script survives several sessions); this joins them."""
    pdir = Path(pdir)
    files = sorted((pdir / "chapters").glob("*.md"))
    if not files:
        sys.exit(f"no chapter files in {pdir / 'chapters'} (expected 01-name.md, 02-name.md, ...)")
    title_file = pdir / "title.txt"
    parts = [f"# {title_file.read_text(encoding='utf-8').strip()}\n"] if title_file.exists() else []
    parts += [f.read_text(encoding="utf-8").strip() + "\n" for f in files]
    (pdir / "script.md").write_text("\n".join(parts), encoding="utf-8")
    proj = parse("\n".join(parts))
    target = None
    plan = pdir / "plan.json"
    if plan.exists():
        try: target = json.loads(plan.read_text()).get("target_words_per_chapter")
        except Exception: pass
    print(f"{'#':>3}  {'chapter':38} {'words':>6} {'min':>5}  broll images sources")
    for i, c in enumerate(proj.chapters, 1):
        flag = ""
        if target and c.words < 0.7 * target: flag = "  <- short"
        print(f"{i:>3}  {c.title[:38]:38} {c.words:>6} {c.words / 150:>5.1f}  {len(c.broll):>5} {len(c.images):>6} {len(c.sources):>7}{flag}")
    print(f"total {proj.words} words = about {proj.words / 150:.0f} min of narration ({len(proj.chapters)} chapters) -> {pdir / 'script.md'}")


def detach(argv, out):
    out.mkdir(parents=True, exist_ok=True)
    args = [a for a in argv if a != "--detach"]
    logf = open(out / "render.log", "w", encoding="utf-8")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, "-u", str(ROOT / "long.py"), *args], stdout=logf, stderr=subprocess.STDOUT, cwd=ROOT,
                     env=dict(os.environ, PYTHONUTF8="1"), **kw)
    print(f"started in the background. Follow with:  python run.py long --status {out}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap, a = parse_args(argv)
    for _stream in (sys.stdout, sys.stderr):
        try: _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    from reel import load_env
    load_env(ROOT / ".env")
    if a.status:
        status(a.status); return
    if a.assemble:
        assemble(a.assemble); return
    if not a.script:
        ap.error("give a project script")
    out = (a.out or Path("out") / a.script.stem).resolve()
    if a.detach:
        detach(argv, out); return
    work = out / "work"; work.mkdir(parents=True, exist_ok=True)
    prog = Progress(work / "progress.json")
    try:
        build(a, out, work, prog)
    except SystemExit as e:
        prog.update("stopped", error=str(e.code) if e.code else None, msg=str(e.code or ""))
        raise
    except Exception as e:
        prog.update("failed", error=f"{type(e).__name__}: {e}")
        raise


def build(a, out, work, prog):
    meta = json.loads(a.meta.read_text(encoding="utf-8")) if a.meta else {}
    look = looks.resolve(a.look or meta.get("look") or "story", meta.get("look_overrides"))
    pick = lambda cli, key: cli if cli is not None else (meta.get(key) if meta.get(key) not in (None, "") else look.get(key))
    a.voice, a.rate, a.pitch = pick(a.voice, "voice"), pick(a.rate, "rate"), pick(a.pitch, "pitch")
    a.accent = pick(a.accent, "accent")
    mood = meta.get("mood") or look["mood"]
    mood = mood if mood in music.MOODS else "cinematic"
    accent = ACCENTS.get(a.accent, ACCENTS["yellow"]) if isinstance(a.accent, str) else tuple(a.accent)
    W, H = SIZES[a.res]; fps = a.fps
    preset, crf = PRESETS[a.quality]
    cpu = os.cpu_count() or 4
    jobs = a.jobs or max(1, min(4, cpu // 2)); threads = max(1, cpu // jobs)
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    upper = look["caption"].get("case") == "upper"

    # 1. parse
    log("1/8 parse")
    proj = parse(a.script.read_text(encoding="utf-8"))
    if a.limit_chapters: proj.chapters = proj.chapters[:a.limit_chapters]
    if not proj.chapters: sys.exit("the script has no chapters or narration")
    title = meta.get("title") or proj.title or a.script.stem
    est_min = proj.words / 150
    log(f"    '{title}': {len(proj.chapters)} chapters, {proj.words} words (~{est_min:.0f} min of narration)")
    if a.plan_only:
        thr = bench(W, H, fps, preset, crf, jobs, threads)
        n_q = sum(len(c.broll) for c in proj.chapters)
        print(json.dumps({"chapters": len(proj.chapters), "words": proj.words, "approx_minutes": round(est_min * 1.12, 1),
                          "approx_shots": int(est_min * 1.12 * 60 / a.shot_seconds), "footage_queries": n_q,
                          "rough_render_speed_x_realtime": round(thr, 1), "rough_render_minutes": round(est_min * 1.12 / thr, 1),
                          "resolution": f"{W}x{H}", "quality": a.quality, "jobs": jobs}, indent=1))
        return
    if est_min * 1.15 > a.max_minutes: sys.exit(f"about {est_min * 1.15:.0f} minutes; over --max-minutes {a.max_minutes:.0f}")

    # 2. narration
    log(f"2/8 narration ({a.tts}, {a.workers} parallel)")
    blocks = proj.blocks
    prog.update("narration", 0, len(blocks), "")
    voice.synthesize(blocks, a.tts, a.voice or "", a.lang, 165, a.rate, None, a.pitch, workers=a.workers,
                     progress=lambda d, n: (prog.update("narration", d, n, ""), log(f"    narration {d}/{n}")))
    for b in blocks:
        if not b.word_times: b.word_times = voice.estimate_times(b.words, b.speech)
    total_s = build_timeline(proj)
    total_s = math.ceil(total_s * fps) / fps
    log(f"3/8 timeline: {total_s / 60:.1f} min, captions from: {blocks[0].timing_source}")

    # 3. captions
    header = ass_header(W, H, look, accent)
    events, lines = [], []
    for ci, ch in enumerate(proj.chapters):
        if ch.card: events += chapter_events(W, H, ci, ch, upper)
        for b in ch.blocks:
            ls = make_lines(b, upper)
            for L in ls: L["chapter"] = ci
            lines += ls
            if b.fact: events += fact_events(W, H, b, upper)
    for L, nxt in zip(lines, lines[1:] + [None]):             # a line never outlives the next one
        if nxt: L["t1"] = min(L["t1"], nxt["t0"] - 0.02)
        events.append(L)

    # 4. footage
    log("4/8 footage and images")
    prog.update("footage", 0, len(proj.chapters), "finding clips")
    default_pool = meta.get("broll") if isinstance(meta.get("broll"), list) else []
    pools = build_pools(proj, (W, H), key, a.broll_dir, default_pool, a.clips_per_query, a.res)
    total_clips = sum(len(p) for p in pools.values())
    if total_clips > a.max_clips: log(f"    ! {total_clips} clips is a lot of disk and download time; lower --clips-per-query")
    used_ids = {c.source_id for p in pools.values() for c in p}
    forced, imgs, credits_img, seen_urls = {}, {}, [], set()
    for ci, ch in enumerate(proj.chapters):
        for b in ch.blocks:
            if b.shot:
                c = forced_clip(b.shot, (W, H), key, a.broll_dir, used_ids)
                if c: forced[id(b)] = c
        imgs[ci] = []
        for q in ch.images:
            try:
                path, credit, url = images.find_image(q, seen_urls)
            except Exception as e:
                log(f"    ! image '{q}' failed: {e}"); continue
            if path: imgs[ci].append((path, credit)); seen_urls.add(url); credits_img.append(credit)
            else: log(f"    ! {credit}")
        prog.update("footage", ci + 1, len(proj.chapters), ch.title)
    has_footage = any(pools.values()) or bool(forced)
    log(f"    {sum(len(p) for p in pools.values())} clips in pools, {sum(len(v) for v in imgs.values())} images")

    # 5. plan
    shots = plan_shots(proj, lines, total_s, fps, a.shot_seconds)
    assign_sources(proj, shots, pools, imgs, forced, fps)
    for s in shots:
        if s["kind"] == "image": s["image"] = prepare_still(s["image"], W, H, work)
    for s in shots:
        h = (s["chapter"] * 47) % 360
        s["g"] = ("0x16222e", "0x2e2216") if h % 2 else ("0x1d1a2e", "0x2e1a24")
    gates = long_gates(proj, shots, lines, total_s, fps, has_footage, meta, pools)
    (out / "gates.json").write_text(json.dumps(gates, indent=2))
    log("5/8 quality gates: " + ("PASS" if gates["passed"] else "FAIL"))
    for m in gates["hard_failures"]: log(f"    ✗ {m}")
    for m in gates["warnings"]: log(f"    ! {m}")
    if not gates["passed"] and not a.force: sys.exit("fix the above (or use --force)")
    if a.stop_after == "plan":
        prog.update("plan", 1, 1, f"{len(shots)} shots, {total_s / 60:.1f} min", 0, finished=True)
        log(f"stopped after planning: {len(shots)} shots, {total_s / 60:.1f} min"); return

    # 6. audio
    log("6/8 audio")
    prog.update("audio", 0, 1, "voice track")
    voice_wav = work / "voice.wav"
    write_voice(proj, voice_wav, total_s)
    music_credits = []
    bed = None
    if a.music == "on":
        tracks = list(a.music_file or [])
        ms = a.music_search or meta.get("music_search")
        if not tracks and ms:
            for k, q in enumerate(([ms] if isinstance(ms, str) else ms)):
                for pick_n in range(1, 3 if len([ms] if isinstance(ms, str) else ms) == 1 else 2):
                    try:
                        path, msg = musicsearch.find_track(q, pick=pick_n)
                    except Exception as e:
                        path, msg = None, f"music search failed: {e}"
                    if path and path not in tracks: tracks.append(path); music_credits.append(msg)
                    elif not path: log(f"    ! {msg}")
        bed = work / "bed.wav"
        build_music_bed(bed, total_s, tracks, mood, title)
        if not tracks: log(f"    using the synthesized '{mood}' bed")
    audio = work / "audio.m4a"
    t_mix = time.time()
    mix_audio(voice_wav, bed, audio, a.music_volume)
    log(f"    audio mixed in {time.time() - t_mix:.0f}s")
    if a.stop_after == "audio":
        prog.update("audio", 1, 1, "audio mixed", 0, finished=True)
        log(f"stopped after audio: {audio}"); return

    # 7. video
    log(f"7/8 render shots ({W}x{H}, {a.quality}, {jobs} parallel)")
    grade = strip_vignette(look.get("grade_filter", ""))
    sd = render_shots(shots, work, header, events, W, H, fps, grade, look.get("cut", "flash"),
                      look["camera"].get("amount", 1.0), preset, crf, jobs, threads, prog, None)
    prog.update("assemble", 0, 1, "joining shots")
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{(sd / s['file']).as_posix()}'\n" for s in shots), encoding="utf-8")
    silent = work / "video_silent.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)], check=True)
    final = out / "video.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c", "copy",
                    "-shortest", "-movflags", "+faststart", str(final)], check=True)

    # 8. YouTube package
    log("8/8 chapters, description, captions, thumbnail")
    chap = [f"{hms(round(c.start))} {c.title}" for c in proj.chapters]
    if proj.chapters[0].start > 0 or len(chap) < 3:
        pass
    (out / "chapters.txt").write_text("\n".join(chap) + "\n", encoding="utf-8")
    (out / "captions.srt").write_text("\n".join(
        f"{i}\n{srt_time(L['first'] - 0.05)} --> {srt_time(L['last'] + 0.2)}\n{L['plain']}\n" for i, L in enumerate(lines, 1)), encoding="utf-8")
    sources = [(c.title, c.sources) for c in proj.chapters if c.sources]
    desc = [meta.get("description", "").strip(), "", "Chapters:", *chap]
    if sources: desc += ["", "Sources:"] + [f"- {t}: {u}" for t, us in sources for u in us]
    foot_credits = sorted({c.credit for p in pools.values() for c in p} | {s["clip"].credit for s in shots if s["kind"] == "clip"})
    cr = [c for c in foot_credits if c] + credits_img + music_credits
    if cr: desc += ["", "Credits:"] + [f"- {c}" for c in cr]
    if meta.get("disclosure"): desc += ["", meta["disclosure"]]
    if meta.get("tags"): desc += ["", "Tags: " + ", ".join(meta["tags"])]
    (out / "description.txt").write_text("\n".join(desc).strip() + "\n", encoding="utf-8")
    (out / "credits.txt").write_text("\n".join(cr) + "\n", encoding="utf-8")
    first = next((s for s in shots if s["kind"] == "clip"), None)
    if first is not None:
        make_thumbnail(out / "thumbnail.png", first["clip"].path, first["ss"] + 1.0, meta.get("thumb_text") or title, accent)
    else:
        make_thumbnail(out / "thumbnail.png", sd / shots[0]["file"], 0.2, meta.get("thumb_text") or title, accent)
    (out / "timeline.json").write_text(json.dumps({
        "title": title, "duration_s": total_s, "chapters": [{"title": c.title, "start": round(c.start, 2), "end": round(c.end, 2)} for c in proj.chapters],
        "shots": [{"t0": round(s["t0"], 2), "t1": round(s["t1"], 2), "kind": s["kind"], "motion": s["motion"],
                   "src": (s["clip"].credit if s["kind"] == "clip" else None)} for s in shots]}, indent=1))
    prog.update("done", 1, 1, f"{total_s / 60:.1f} min video", 0, finished=True)
    log(f"done → {final}  ({total_s / 60:.1f} min)")
