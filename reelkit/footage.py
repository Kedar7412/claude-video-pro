"""B-roll: find one clip per scene (Pexels stock video, a local folder, or explicit paths), cache downloads,
and stream frames through a moving virtual camera (push-in, pull-out, pans, cut punches, shakes).

Pexels needs a free API key (PEXELS_API_KEY in the environment or in .env). Pexels' license allows free commercial
use without attribution; credits are still written to credits.txt.
"""
import hashlib, json, math, re, subprocess, sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .common import FFMPEG, FPS

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "broll"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
STOP = set("a an the and or but of to in on at for with from by is are was were be been it its this that these those you your "
           "i me my we our they them their he she his her not no do does did can will just so than then very more most "
           "how what why when where who which into out up down over about after before".split())


def log(msg): print(msg, file=sys.stderr, flush=True)


@dataclass
class Clip:
    path: Path
    duration: float
    credit: str = ""
    source_id: str = ""


def probe_duration(path) -> float:
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True, errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def orientation_for(W, H): return "landscape" if W / H > 1.2 else "portrait"


def keywords(text, n=4):
    ws = [w for w in re.findall(r"[a-zA-Z]+", text.lower()) if w not in STOP and len(w) > 2]
    return " ".join(sorted(dict.fromkeys(ws), key=len, reverse=True)[:n])


# ───────────────────────── Pexels ─────────────────────────
def _pexels_search(query, orientation, key):
    import requests
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"search_{hashlib.sha1(f'{query}|{orientation}'.encode()).hexdigest()[:16]}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key}, timeout=30,
                     params={"query": query, "orientation": orientation, "per_page": 15})
    if r.status_code == 401:
        raise RuntimeError("Pexels rejected the API key (401). Check PEXELS_API_KEY.")
    r.raise_for_status()
    data = r.json().get("videos", [])
    f.write_text(json.dumps(data))
    return data


def _pick_file(files, W, H):
    mp4 = [f for f in files if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
    if not mp4:
        return None
    # smallest file that still covers the frame after a cover-crop (avoids 4K downloads)
    def covers(f):
        s = max(W / f["width"], H / f["height"])
        return s <= 1.05
    good = [f for f in mp4 if covers(f)]
    return min(good, key=lambda f: f["width"] * f["height"]) if good else max(mp4, key=lambda f: f["width"] * f["height"])


def _download(url, dst):
    import requests
    tmp = dst.with_suffix(".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    tmp.replace(dst)


def pexels_clip(query, size, key, used, min_dur):
    W, H = size
    q, _, pick = query.partition("#")
    pick = int(pick) - 1 if pick.strip().isdigit() else 0
    vids = _pexels_search(q.strip(), orientation_for(W, H), key)
    cands = [v for v in vids if str(v.get("id")) not in used]
    if not cands:
        return None
    longer = [v for v in cands if v.get("duration", 0) >= min_dur]
    order = longer + [v for v in cands if v not in longer]
    v = order[min(pick, len(order) - 1)]
    f = _pick_file(v.get("video_files", []), W, H)
    if not f:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / f"pexels_{v['id']}_{f.get('id', 'x')}.mp4"
    if not dst.exists():
        log(f"    downloading clip {v['id']} for '{q.strip()}' ({f['width']}x{f['height']})")
        _download(f["link"], dst)
    user = (v.get("user") or {}).get("name", "unknown")
    return Clip(dst, float(v.get("duration") or probe_duration(dst)), f"{user} on Pexels: {v.get('url', '')}", str(v["id"]))


# ───────────────────────── local clips ─────────────────────────
def local_clip(files, query, used):
    qw = set(re.findall(r"[a-z]+", query.lower())) - STOP
    def score(p):
        nw = set(re.findall(r"[a-z]+", p.stem.lower()))
        return len(qw & nw)
    fresh = [p for p in files if str(p) not in used] or files
    best = max(fresh, key=lambda p: (score(p), -files.index(p)))
    return Clip(best, probe_duration(best), f"local file {best.name}", str(best))


def find_clips(scenes, size, key=None, broll_dir=None):
    """One Clip (or None) per scene. Explicit paths win, then a local folder, then Pexels."""
    local = []
    if broll_dir:
        d = Path(broll_dir)
        local = sorted(p for p in d.iterdir() if p.suffix.lower() in VIDEO_EXT) if d.is_dir() else []
        if not local:
            log(f"    ! no video files found in {broll_dir}")
    used, out = set(), []
    for s in scenes:
        q = (s.broll or "").strip()
        clip = None
        try:
            if q and Path(q).suffix.lower() in VIDEO_EXT and Path(q).exists():
                clip = Clip(Path(q), probe_duration(q), f"local file {Path(q).name}", q)
            elif local:
                clip = local_clip(local, q or s.text, used)
            elif key:
                clip = pexels_clip(q or keywords(s.text), size, key, used, s.dur)
        except Exception as e:
            log(f"    ! footage for scene '{s.text[:40]}' failed: {e}")
        if clip:
            used.add(clip.source_id)
        out.append(clip)
    # a scene without footage borrows another scene's clip (different moment, different camera move)
    have = [c for c in out if c]
    if have:
        out = [c or have[i % len(have)] for i, c in enumerate(out)]
    return out


# ───────────────────────── frame streaming + camera ─────────────────────────
def ease_io(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def spring(t, k=260.0, d=22.0):
    if t <= 0: return 0.0
    w0 = math.sqrt(k); z = d / (2 * w0)
    if z < 1:
        wd = w0 * math.sqrt(1 - z * z)
        return 1 - math.exp(-z * w0 * t) * (math.cos(wd * t) + z * w0 / wd * math.sin(wd * t))
    return 1 - math.exp(-w0 * t) * (1 + w0 * t)


MOTIONS = ["push", "pan_r", "pull", "push", "pan_l", "rise"]


class SceneVideo:
    """Decodes one clip at Z x the output size (cover-cropped, graded) and returns camera-framed frames."""
    Z = 1.18

    def __init__(self, clip, W, H, dur, idx, grade="eq=contrast=1.07:saturation=1.15:brightness=-0.02,vignette=angle=PI/5",
                 camera=None):
        cam = camera or {}
        self.amount, self.punch = cam.get("amount", 1.0), cam.get("punch", 1.0)
        self.shake_on, self.exit_zoom = cam.get("shake", True), cam.get("exit_zoom", True)
        self.clip, self.W, self.H, self.dur = clip, W, H, dur
        self.SW, self.SH = int(W * self.Z) // 2 * 2, int(H * self.Z) // 2 * 2
        self.motion = MOTIONS[idx % len(MOTIONS)]
        cd = max(clip.duration, 0.1)
        # start a little into the clip (skips fade-ins); a reused clip starts at a different moment
        spare = max(0.0, cd - dur)
        self.off = min(spare, 0.6 + spare * ((idx * 0.37) % 1) * 0.5)
        self.grade = grade
        self.proc, self.pos, self.cur = None, -1, None
        self.nbytes = self.SW * self.SH * 3

    def _open(self, idx):
        self.close()
        cd = max(self.clip.duration, 0.1)
        ss = (self.off + idx / FPS) % cd
        vf = (f"scale={self.SW}:{self.SH}:force_original_aspect_ratio=increase:flags=bicubic,crop={self.SW}:{self.SH},fps={FPS}")
        if self.grade:
            vf += "," + self.grade
        cmd = [FFMPEG, "-v", "error", "-stream_loop", "-1", "-ss", f"{ss:.3f}", "-i", str(self.clip.path),
               "-t", f"{max(0.5, self.dur - idx / FPS + 0.5):.3f}", "-an", "-vf", vf,
               "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.nbytes * 2)
        self.pos = idx - 1

    def raw(self, idx):
        if self.proc is None or idx < self.pos:
            self._open(idx)
        while self.pos < idx:
            buf = self.proc.stdout.read(self.nbytes)
            if len(buf) < self.nbytes:      # clip ended early: hold the last frame
                if self.cur is None:
                    self.cur = np.zeros((self.SH, self.SW, 3), np.uint8)
                self.pos = idx
                break
            self.cur = np.frombuffer(buf, np.uint8).reshape(self.SH, self.SW, 3)
            self.pos += 1
        return self.cur

    def frame(self, lt, shakes=()):
        """PIL frame at local time lt with the camera applied."""
        a = self.raw(max(0, int(round(lt * FPS))))
        p = lt / max(self.dur, 0.01)
        Z = self.Z
        m, dx, dy = 1.0, 0.0, 0.0
        A = self.amount
        if self.motion == "push": m = 1.0 + 0.13 * A * ease_io(p)
        elif self.motion == "pull": m = 1.0 + 0.13 * A * (1 - ease_io(p))
        else:
            m = 1.0 + 0.09 * max(A, 0.35)
            span = (1 - 2 * ease_io(p)) * min(1.0, A * 1.2)
            if self.motion == "pan_r": dx = -span
            elif self.motion == "pan_l": dx = span
            else: dy = span
        m += 0.08 * self.punch * (1 - spring(lt, 300, 24))          # punch-in on the cut
        tail = self.dur - lt
        if self.exit_zoom and 0 <= tail < 0.14:
            m += 0.07 * ((0.14 - tail) / 0.14) ** 2                  # zoom-through into the next cut
        m = min(max(m, 1.0), Z)
        cw, ch = self.SW / m, self.SH / m
        mxp, myp = (self.SW - cw) / 2, (self.SH - ch) / 2
        ox, oy = dx * mxp, dy * myp
        for t0 in (shakes if self.shake_on else ()):                 # small shake on stressed words
            dt = lt - t0
            if 0 <= dt < 0.3:
                amp = 14 * math.exp(-dt * 11)
                ox += amp * math.sin(dt * 95); oy += amp * math.cos(dt * 71)
        x0 = min(max(self.SW / 2 - cw / 2 + ox, 0), self.SW - cw)
        y0 = min(max(self.SH / 2 - ch / 2 + oy, 0), self.SH - ch)
        im = Image.fromarray(a)
        return im.resize((self.W, self.H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))

    def close(self):
        if self.proc:
            try:
                self.proc.stdout.close(); self.proc.kill(); self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None
