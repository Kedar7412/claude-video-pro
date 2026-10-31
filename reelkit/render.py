"""Frame renderer: every frame is a pure function of time.
Four layouts (hook, card, stat, cta), a lip-synced paper host, script-matched props, and any aspect ratio."""
import math, os, re
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import figures
from .common import FPS, SR
from .script import stat_index

PALETTES = {
    "studio": [("#F4EBDD", "#1F1B16", "#E4572E"), ("#16324F", "#F7F3E8", "#FFB627"),
               ("#2E4A3F", "#F4EFE3", "#F2A65A"), ("#3B1F2B", "#FBEFE5", "#FF6B6B")],
    "ink":    [("#0E0E10", "#F5F5F5", "#7CFFB2"), ("#18181B", "#FAFAFA", "#6EA8FF")],
    "ochre":  [("#E9B44C", "#1B1B1B", "#9B2915"), ("#F6E7C1", "#2A1E10", "#C8553D")],
}
FONT_CANDIDATES = [
    "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def hex2rgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def lum(c): return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255
def lerp(a, b, t): return a + (b - a) * t
def clamp01(x): return min(max(x, 0.0), 1.0)
def ease_out(x): x = clamp01(x); return 1 - (1 - x) ** 3


def spring(t, k=210.0, d=22.0):
    """Closed-form damped spring 0->1 as a pure function of time (small overshoot)."""
    if t <= 0: return 0.0
    w0 = math.sqrt(k); z = d / (2 * w0)
    if z < 1:
        wd = w0 * math.sqrt(1 - z * z)
        return 1 - math.exp(-z * w0 * t) * (math.cos(wd * t) + z * w0 / wd * math.sin(wd * t))
    return 1 - math.exp(-w0 * t) * (1 + w0 * t)


def load_font(size, path):
    for p in ([path] if path else []) + FONT_CANDIDATES:
        if p and os.path.exists(p):
            f = ImageFont.truetype(p, size)
            try: f.set_variation_by_name("Bold")
            except Exception: pass
            return f
    return ImageFont.load_default()


def wrap(measure, words, font, max_w):
    lines, cur = [], []
    for i, w in words:
        trial = " ".join(x for _, x in cur + [(i, w)])
        if cur and measure.textlength(trial, font=font) > max_w:
            lines.append(cur); cur = []
        cur.append((i, w))
    if cur: lines.append(cur)
    return lines


def format_count(token: str, p: float) -> str:
    """Count-up for tokens like $27, 200,000+, 10x, 3.5%."""
    m = re.match(r"^([^\d]*)([\d,\.]+)(.*)$", token.strip(".,!?;:"))
    if not m: return token
    pre, num, post = m.groups()
    num_clean = num.replace(",", "").rstrip(".")
    try: val = float(num_clean)
    except ValueError: return token
    dec = len(num_clean.split(".")[1]) if "." in num_clean else 0
    cur = val * clamp01(p)
    s = f"{cur:,.{dec}f}" if "," in num else f"{cur:.{dec}f}"
    return f"{pre}{s}{post}"


class Geo:
    """Per-aspect-ratio geometry: where text, host and props live, kept clear of platform UI."""
    def __init__(self, W, H):
        self.W, self.H = W, H
        r = W / H
        if r > 1.2:                                   # 16:9 — host column on the left, text on the right
            self.name = "16:9"; self.mx = 100; self.bar_y = 60; self.chip_y = 90
            self.text = (720, 150, W - 100, H - 110)
            self.full = (100, 150, W - 100, H - 110)
            self.host = (380, H - 90, 1.12)
            self.prop = (380, 330, 270)
            self.ledge = (100, 660, H - 90)
            self.handle = (720, H - 72)
        elif r > 0.9:                                 # 1:1
            self.name = "1:1"; self.mx = 80; self.bar_y = 56; self.chip_y = 86
            self.text = (80, 86 + 84 + 24, W - 80, H - 100 - 252)
            self.full = (80, 86 + 84 + 24, W - 80, H - 100)
            self.host = (240, H - 100, 0.58)
            self.prop = (W - 240, H - 100 - 125, 220)
            self.ledge = (80, W - 80, H - 100)
            self.handle = (80, H - 68)
        elif r > 0.7:                                 # 4:5
            self.name = "4:5"; self.mx = 80; self.bar_y = 100; self.chip_y = 140
            self.text = (80, 140 + 84 + 26, W - 80, H - 100 - 330)
            self.full = (80, 140 + 84 + 26, W - 80, H - 100)
            self.host = (250, H - 100, 0.8)
            self.prop = (W - 250, H - 100 - 170, 270)
            self.ledge = (80, W - 80, H - 100)
            self.handle = (80, H - 70)
        else:                                         # 9:16 — keep clear of IG's top bar and bottom/right buttons
            self.name = "9:16"; self.mx = 90; self.bar_y = 200; self.chip_y = 250
            self.text = (90, 400, W - 90, H - 480 - 410)
            self.full = (90, 400, W - 90, H - 480)
            self.host = (285, H - 480, 1.0)
            self.prop = (W - 270, H - 480 - 210, 310)
            self.ledge = (90, W - 90, H - 480)
            self.handle = (90, H - 480 + 60)


class Renderer:
    def __init__(self, scenes, palette, handle, font_path, size=(1080, 1920), host="paper", props=True,
                 host_photo=None, voice_pcm=None):
        self.scenes, self.handle, self.font_path = scenes, handle, font_path
        self.W, self.H = size
        self.g = Geo(*size)
        self.pal = PALETTES[palette]
        self.host_mode, self.props_on = host, props
        self.photo = None
        if host_photo:
            im = Image.open(host_photo).convert("RGB")
            self.photo = ImageOps.fit(im, (360, 360), Image.LANCZOS)
        self.fonts = {}
        self.measure = ImageDraw.Draw(Image.new("RGB", (4, 4)))
        self.layouts = [self._layout(s) for s in scenes]
        self.total = scenes[-1].start + scenes[-1].dur
        self.prop_cache = {}
        self.env = None
        if voice_pcm is not None:
            self.set_voice(voice_pcm)

    # ── audio-reactive mouth ──
    def set_voice(self, pcm):
        n = int(len(pcm) / SR * FPS) + 2
        hop = SR // FPS
        x = np.abs(pcm[: (len(pcm) // hop) * hop].astype(np.float32)).reshape(-1, hop).mean(axis=1)
        x = np.convolve(x, np.ones(3) / 3, mode="same")
        peak = np.percentile(x, 95) or 1.0
        self.env = np.clip(x / peak, 0, 1)

    def amp(self, t):
        if self.env is None:
            return 0.0
        i = int(t * FPS)
        return float(self.env[min(i, len(self.env) - 1)]) if i >= 0 else 0.0

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = load_font(size, self.font_path)
        return self.fonts[size]

    # ── layout ──
    def _fit(self, words, max_w, max_h, hi, lo, step=6, lh_factor=1.22):
        for size in range(int(hi), int(lo) - 1, -step):
            lines = wrap(self.measure, words, self.font(size), max_w)
            if len(lines) * size * lh_factor <= max_h:
                return size, lines
        return int(lo), wrap(self.measure, words, self.font(int(lo)), max_w)

    def _layout(self, s):
        g = self.g
        idx = list(enumerate(s.words))
        x0, y0, x1, y1 = g.text
        tw, th = x1 - x0, y1 - y0
        lay = {"num": None}
        if s.kind == "hook":
            size, lines = self._fit(idx, tw - 70, th, 150, 70)
        elif s.kind == "cta":
            fx0, fy0, fx1, fy1 = g.full
            size, lines = self._fit(idx, fx1 - fx0 - 40, (fy1 - fy0) * 0.5, 118, 64)
        elif s.kind == "stat":
            ni = stat_index(s.words)
            lay["num"] = ni
            ns = int(min(300, th * 0.36))
            while ns > 110 and self.measure.textlength(s.words[ni].strip(".,!?;:"), font=self.font(ns)) > tw - 80:
                ns -= 10
            lay["num_size"] = ns
            size, lines = self._fit(idx, tw - 80, max(120, th - ns * 1.15 - 80), 92, 48)
        else:
            size, lines = self._fit(idx, tw - 80, th - 40, 124, 48)
        lay.update(size=size, lines=lines)
        return lay

    # ── drawing helpers ──
    def _words(self, d, s, lay, lt, y0, colors, cx, align="center", left=0, underline=True):
        f = self.font(lay["size"]); size = lay["size"]; lh = size * 1.22
        base, hi = colors
        y = y0
        sp = d.textlength(" ", font=f)
        for line in lay["lines"]:
            widths = [d.textlength(w + " ", font=f) for _, w in line]
            x = cx - (sum(widths) - sp) / 2 if align == "center" else left
            for (wi, w), ww in zip(line, widths):
                ws, we = s.word_times[wi]
                if lt >= ws - 0.02:
                    pop = spring(lt - ws, 420, 24)
                    active = ws <= lt < we + 0.08
                    lift = (1 - min(pop, 1)) * 30
                    d.text((x, y + lift), w, font=f, fill=(*(hi if active else base), int(255 * min(1, pop * 1.6))))
                    if underline and active:
                        wid = (ww - sp) * ease_out((lt - ws) / 0.12)
                        d.rounded_rectangle([x, y + size * 1.13, x + wid, y + size * 1.13 + max(8, size // 12)],
                                            radius=6, fill=(*hi, 255))
                else:
                    d.text((x, y), w, font=f, fill=(*base, 30))
                x += ww
            y += lh
        return y

    def _background(self, d, kind, t, si, accent, fg):
        W, H = self.W, self.H
        if kind == "hook":   # sliding diagonal stripes
            off = (t * 90) % 160
            for k in range(-4, int(W / 160) + 10):
                x = k * 160 + off
                d.polygon([(x, 0), (x + 55, 0), (x + 55 - H * 0.36, H), (x - H * 0.36, H)], fill=(*accent, 22))
        elif kind == "stat":   # breathing dot grid
            for gx in range(0, W + 120, 120):
                for gy in range(0, H + 120, 120):
                    r = 5 + 3 * math.sin(t * 2 + gx * 0.01 + gy * 0.013)
                    d.ellipse([gx - r, gy - r, gx + r, gy + r], fill=(*accent, 60))
        elif kind == "cta":
            R = max(W, H) * 0.6
            for k in range(6):
                r = ((t * 260 + k * 190) % R)
                d.ellipse([W / 2 - r, H * 0.62 - r, W / 2 + r, H * 0.62 + r], outline=(*fg, int(70 * (1 - r / R))), width=6)
        else:
            for k in range(5):
                ph = si * 1.7 + k * 1.3
                cx = W * (0.15 + 0.7 * ((k * 0.37 + 0.05 * math.sin(t * 0.6 + ph)) % 1))
                cy = H * (0.1 + 0.8 * ((k * 0.23 + 0.04 * math.cos(t * 0.5 + ph)) % 1))
                r = 120 + 70 * ((k * 53) % 5) / 4 + 12 * math.sin(t * 1.2 + ph)
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*accent, 38))

    def _emphasis(self, s, lt):
        e = 0.0
        for w, (ws, _) in zip(s.words, s.word_times):
            if lt >= ws and len(w) >= 4:
                e = max(e, math.exp(-(lt - ws) * 5.0))
        return e

    def _draw_host(self, img, s, lt, t, accent, fg, bg):
        g = self.g
        cx, base, sc = g.host
        has_prop = bool(self.props_on and s.prop)
        if g.name != "16:9" and not has_prop:
            cx = self.W / 2
        layer = figures.make_host_layer(accent, (31, 27, 22), t, self.amp(t), self._emphasis(s, lt), self.photo)
        w, h = int(figures.HOST_W * sc), int(figures.HOST_H * sc)
        layer = layer.resize((w, h), Image.LANCZOS)
        pop = spring(lt, 120, 16)
        img.paste(layer, (int(cx - w / 2), int(base - h * min(1, 0.25 + 0.75 * pop) + 6)), layer)
        # paper ledge hides the crop edge and makes the host look like it is standing behind a desk
        lx0, lx1, ly = g.ledge
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle([lx0, ly - 4, lx1, ly + 26], radius=14, fill=(*fg, 255))
        d.rounded_rectangle([lx0, ly - 4, lx1, ly + 6], radius=6, fill=(*accent, 255))

    def _draw_prop(self, img, s, si, lt, t, accent, fg, bg):
        g = self.g
        key = (s.prop, si)
        if key not in self.prop_cache:
            self.prop_cache[key] = figures.make_prop(s.prop, accent, fg if lum(fg) < 0.5 else (31, 27, 22), lambda n: self.font(n))
        pop = spring(lt - 0.2, 190, 14)
        if pop <= 0.02:
            return
        cx, cy, size = g.prop
        sz = max(4, int(size * pop))
        im = self.prop_cache[key].resize((sz, sz), Image.LANCZOS)
        im = im.rotate(5 * math.sin(t * 1.6 + si), resample=Image.BICUBIC, expand=True)
        y = cy + 10 * math.sin(t * 2.0 + si)
        img.paste(im, (int(cx - im.width / 2), int(y - im.height / 2)), im)

    # ── frame ──
    def frame(self, t: float) -> Image.Image:
        W, H, g = self.W, self.H, self.g
        si = next((i for i, s in enumerate(self.scenes) if t < s.start + s.dur), len(self.scenes) - 1)
        s, lay = self.scenes[si], self.layouts[si]
        lt = t - s.start
        bg, fg, accent = (hex2rgb(c) for c in self.pal[si % len(self.pal)])
        kind = s.kind
        if kind == "cta":   # inverted: accent background
            dark = bg if lum(bg) < 0.5 else fg
            bg, fg, accent = accent, dark, dark
        img = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(img, "RGBA")
        self._background(d, kind, t, si, accent if kind != "cta" else fg, fg)
        mx = g.mx
        acc_c = accent if kind != "cta" else fg

        d.rectangle([mx, g.bar_y, W - mx, g.bar_y + 12], fill=(*fg, 40))
        d.rectangle([mx, g.bar_y, mx + max(0.0, (W - 2 * mx) * t / self.total), g.bar_y + 12], fill=(*acc_c, 255))
        if kind != "cta":
            chip_t = spring(lt, 260, 24)
            chip = "WATCH THIS" if kind == "hook" else f"{si + 1:02d} / {len(self.scenes):02d}"
            cf = self.font(40)
            cw = d.textlength(chip, font=cf) + 60
            cy0 = g.chip_y - 10 - (1 - chip_t) * 40
            d.rounded_rectangle([mx, cy0, mx + cw, cy0 + 84], radius=42, fill=(*accent, 255))
            d.text((mx + 30, cy0 + 20), chip, font=cf, fill=(*bg, 255))

        card_dark = lum(bg) < 0.5
        card_fill = tuple(int(lerp(c, 255, 0.12)) for c in bg) if card_dark else (255, 252, 246)
        txt = (245, 245, 245) if card_dark else (24, 22, 20)
        x0, y0, x1, y1 = g.text
        tcx = (x0 + x1) / 2

        if kind == "card":
            card_t = spring(lt, 150, 19)
            mid = (y0 + y1) / 2
            half = (y1 - y0) / 2 * (0.6 + 0.4 * card_t)
            alpha = int(255 * clamp01(lt / 0.2))
            d.rounded_rectangle([x0 + 14, mid - half + 22, x1 + 14, mid + half + 22], radius=56, fill=(0, 0, 0, int(60 * alpha / 255)))
            d.rounded_rectangle([x0, mid - half, x1, mid + half], radius=56, fill=(*card_fill, alpha), outline=(*fg, alpha), width=5)
            n = len(lay["lines"])
            self._words(d, s, lay, lt, mid - n * lay["size"] * 1.22 / 2, (txt, accent), tcx)

        elif kind == "hook":
            n = len(lay["lines"]); th = n * lay["size"] * 1.22
            ty = (y0 + y1) / 2 - th / 2
            d.rounded_rectangle([x0, ty, x0 + 18, ty + th * ease_out(lt / 0.5)], radius=9, fill=(*accent, 255))
            self._words(d, s, lay, lt, ty, (fg, accent), tcx, align="left", left=x0 + 56)

        elif kind == "stat":
            ni = lay["num"]; ns = lay["num_size"]; nf = self.font(ns)
            ws, _ = s.word_times[ni]
            token = s.words[ni].strip(".,!?;:")
            shown = format_count(token, (lt - ws) / 0.8) if lt >= ws else format_count(token, 0)
            pop = spring(lt - ws + 0.05, 300, 17) if lt >= ws - 0.05 else 0
            cy = y0 + ns * 0.62
            vw = d.textlength(shown, font=nf)
            d.text((tcx - vw / 2, cy - ns * 0.55 + (1 - min(pop, 1)) * 60), shown, font=nf,
                   fill=(*accent, int(255 * min(1, pop * 1.5))))
            ry = cy + ns * 0.62
            d.rounded_rectangle([x0 + 80, ry, x1 - 80, ry + 10], radius=5, fill=(*fg, 60))
            self._words(d, s, lay, lt, ry + 40, (fg, accent), tcx)

        else:  # cta
            fx0, fy0, fx1, fy1 = g.full
            n = len(lay["lines"]); th = n * lay["size"] * 1.22
            label = self.handle or "FOLLOW FOR MORE"
            pf = self.font(58)
            total_h = th + 70 + 120
            ty = fy0 + (fy1 - fy0 - total_h) / 2
            end = self._words(d, s, lay, lt, ty, (fg, fg), (fx0 + fx1) / 2, underline=False)
            pw = d.textlength(label, font=pf) + 100
            pulse = 1 + 0.04 * math.sin(lt * 7) * clamp01(lt / 0.6)
            px, py = ((fx0 + fx1) - pw * pulse) / 2, end + 70
            d.rounded_rectangle([px, py, px + pw * pulse, py + 120 * pulse], radius=60, fill=(*fg, 255))
            d.text((((fx0 + fx1) - d.textlength(label, font=pf)) / 2, py + 28 * pulse), label, font=pf, fill=(*bg, 255))

        if kind != "cta":
            if self.host_mode != "none":
                self._draw_host(img, s, lt, t, accent, fg, bg)
            if self.props_on and s.prop:
                self._draw_prop(img, s, si, lt, t, accent, fg, bg)
            if self.handle:
                ImageDraw.Draw(img, "RGBA").text(g.handle, self.handle, font=self.font(40), fill=(*fg, 220))

        if si and lt < 0.38:   # wipe from the previous scene (accent panel retreating right)
            p = ease_out(lt / 0.38)
            ImageDraw.Draw(img, "RGBA").rectangle([W * p, 0, W, H], fill=(*acc_c, 255))
        return img

    def blurred(self, t: float, sub: int) -> bytes:
        """Average `sub` sub-frames across the shutter interval for real motion blur."""
        if sub <= 1:
            return self.frame(t).tobytes()
        acc = None
        for k in range(sub):
            a = np.asarray(self.frame(max(0.0, t - (sub - 1 - k) / (sub * FPS) * 0.8)), dtype=np.uint16)
            acc = a if acc is None else acc + a
        return (acc // sub).astype(np.uint8).tobytes()
