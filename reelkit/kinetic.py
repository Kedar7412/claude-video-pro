"""Footage style: full-screen b-roll with a moving camera and bold kinetic captions.

Captions show 1-3 words at a time, the spoken word lights up, stressed (*marked*) words get their own big beat,
numbers count up, and the end card puts the handle in a pill. Every frame is still a function of time."""
import math, re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .common import FPS
from .footage import SceneVideo, spring
from .render import format_count, load_font
from .script import stat_index

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
ACCENTS = {"yellow": (255, 214, 10), "green": (92, 255, 122), "orange": (255, 122, 48), "pink": (255, 92, 170),
           "cyan": (64, 224, 255)}
WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def _font(path, size, variation=None):
    f = ImageFont.truetype(str(path), size)
    if variation:
        try: f.set_variation_by_name(variation)
        except Exception: pass
    return f


def pick_fonts(texts, override=None):
    """(caption font loader, UI font loader). Anton for Latin text, Montserrat for Cyrillic/Vietnamese, else system."""
    allt = " ".join(texts)
    anton, mont = FONTS / "Anton-Regular.ttf", FONTS / "Montserrat[wght].ttf"
    latin = all(ord(c) < 0x250 or c in "’‘“”–—…" for c in allt)
    cyr_or_vi = all(ord(c) < 0x250 or 0x400 <= ord(c) < 0x530 or 0x1E00 <= ord(c) < 0x1F00 or c in "’‘“”–—…" for c in allt)
    if override:
        cap = lambda n: load_font(n, override); ui = cap
    elif latin and anton.exists():
        cap = lambda n: _font(anton, n); ui = lambda n: _font(mont, n, "ExtraBold") if mont.exists() else load_font(n, None)
    elif cyr_or_vi and mont.exists():
        cap = lambda n: _font(mont, n, "Black"); ui = lambda n: _font(mont, n, "ExtraBold")
    else:
        cap = lambda n: load_font(n, None); ui = cap
    return cap, ui


def chunk_scene(s, max_words=3, max_chars=16):
    """Group a scene's words into caption beats. A stressed word always gets a beat of its own."""
    chunks, cur = [], []
    def push():
        if cur: chunks.append(list(cur)); cur.clear()
    for i, w in enumerate(s.words):
        if i in s.emph and (i - 1) not in s.emph:
            push()
        n = sum(len(s.words[j]) + 1 for j in cur)
        if cur and (len(cur) >= max_words or n + len(w) > max_chars):
            push()
        cur.append(i)
        if i in s.emph and (i + 1) not in s.emph:
            push()
        elif w[-1] in ",.!?;:—":
            push()
    push()
    return chunks


class Geo:
    def __init__(self, W, H):
        r = W / H
        if r > 1.2:   self.cap_y, self.title_y, self.mx, self.bar_y, self.num_y, self.base = H * 0.72, 60, 140, 0, H * 0.40, 130
        elif r > 0.9: self.cap_y, self.title_y, self.mx, self.bar_y, self.num_y, self.base = H * 0.66, 70, 80, 0, H * 0.38, 120
        elif r > 0.7: self.cap_y, self.title_y, self.mx, self.bar_y, self.num_y, self.base = H * 0.64, 100, 80, 0, H * 0.38, 135
        else:         self.cap_y, self.title_y, self.mx, self.bar_y, self.num_y, self.base = H * 0.60, 250, 90, 0, H * 0.38, 150
        self.handle_y = self.cap_y + self.base * 1.6


class FootageRenderer:
    def __init__(self, scenes, clips, size, handle="", title="", accent="yellow", font_path=None):
        self.scenes, self.handle, self.title = scenes, handle, (title or "").strip()
        self.W, self.H = size
        self.g = Geo(*size)
        self.accent = ACCENTS.get(accent, ACCENTS["yellow"]) if isinstance(accent, str) else accent
        self.capf, self.uif = pick_fonts([s.text for s in scenes] + [self.title, handle], font_path)
        self._fc = {}
        self.videos = [SceneVideo(c, self.W, self.H, s.dur, i) if c else None for i, (s, c) in enumerate(zip(scenes, clips))]
        self.total = scenes[-1].start + scenes[-1].dur
        self.measure = ImageDraw.Draw(Image.new("RGB", (4, 4)))
        self.chunks = [self._layout_chunks(s) for s in scenes]
        self.layouts = [{"size": min(c["size"] for c in ch)} for ch in self.chunks]   # used by the readability gate
        self.masks = self._masks()

    def font(self, size, ui=False):
        key = (size, ui)
        if key not in self._fc:
            self._fc[key] = (self.uif if ui else self.capf)(size)
        return self._fc[key]

    # ── layout ──
    def _layout_chunks(self, s):
        out = []
        max_w = self.W - 2 * self.g.mx
        for k, idx in enumerate(chunk_scene(s)):
            words = [s.words[i].upper() for i in idx]
            solo = len(idx) == 1 and idx[0] in s.emph
            size = int(self.g.base * (1.45 if solo else 1.0) * (1.12 if s.kind == "hook" else 1.0))
            lines = [list(range(len(words)))]
            while size > 60:
                f = self.font(size)
                if self.measure.textlength(" ".join(words), font=f) <= max_w:
                    lines = [list(range(len(words)))]; break
                if len(words) > 1:   # two balanced lines
                    best = min(range(1, len(words)), key=lambda c: abs(self.measure.textlength(" ".join(words[:c]), font=f)
                                                                      - self.measure.textlength(" ".join(words[c:]), font=f)))
                    l1, l2 = " ".join(words[:best]), " ".join(words[best:])
                    if max(self.measure.textlength(l1, font=f), self.measure.textlength(l2, font=f)) <= max_w:
                        lines = [list(range(best)), list(range(best, len(words)))]; break
                size -= 6
            start = s.word_times[idx[0]][0]
            out.append({"idx": idx, "words": words, "size": size, "lines": lines, "start": start, "solo": solo})
        for a, b in zip(out, out[1:]):
            a["end"] = b["start"]
        if out:
            out[-1]["end"] = s.dur
            out[0]["start"] = min(out[0]["start"], 0.0)
        return out

    def _masks(self):
        """Per-row brightness multipliers (0-256) so captions and title read on any footage."""
        H = self.H
        y = np.arange(H, dtype=np.float32)
        band = 1 - 0.42 * np.exp(-((y - self.g.cap_y) / (H * 0.17)) ** 2)
        if self.title:
            band *= 1 - 0.30 * np.exp(-((y - self.g.title_y) / (H * 0.12)) ** 2)
        normal = (band * 256).astype(np.uint16)[:, None, None]
        end = (band * 0.62 * 256).astype(np.uint16)[:, None, None]
        return {"normal": normal, "end": end}

    # ── drawing ──
    def _text(self, d, xy, txt, f, fill, size):
        sw = max(5, size // 13)
        x, y = xy
        d.text((x, y + size * 0.07), txt, font=f, fill=(0, 0, 0, 120), stroke_width=sw, stroke_fill=(0, 0, 0, 120))
        d.text((x, y), txt, font=f, fill=fill, stroke_width=sw, stroke_fill=BLACK)

    def _captions(self, d, s, lt):
        ch = next((c for c in self.chunks[self.scenes.index(s)] if c["start"] - 0.03 <= lt < c["end"]), None)
        if ch is None:
            return
        pop = spring(lt - ch["start"] + 0.03, 520 if not ch["solo"] else 380, 26 if not ch["solo"] else 18)
        scale = (0.62 + 0.38 * pop) if ch["solo"] else (0.80 + 0.20 * pop)
        size = max(20, int(ch["size"] * scale) // 2 * 2)
        f = self.font(size)
        lh = size * 1.08
        n = len(ch["lines"])
        y = self.g.cap_y - n * lh / 2 + (1 - min(pop, 1)) * 26
        sp = d.textlength(" ", font=f)
        spoken = [gi for gi in ch["idx"] if s.word_times[gi][0] - 0.02 <= lt]
        cur = spoken[-1] if spoken else None          # exactly one word lights up: the one being said now
        for line in ch["lines"]:
            ws = [ch["words"][k] for k in line]
            widths = [d.textlength(w, font=f) for w in ws]
            x = (self.W - (sum(widths) + sp * (len(ws) - 1))) / 2
            for k, w, wd in zip(line, ws, widths):
                gi = ch["idx"][k]
                col = self.accent if (gi in s.emph or gi == cur) else WHITE
                self._text(d, (x, y), w, f, (*col, 255), size)
                x += wd + sp
            y += lh

    def _title(self, d, t):
        if not self.title:
            return
        p = spring(t, 200, 20)
        f = self.font(max(30, int(self.g.base * 0.36)), ui=True)
        txt = self.title.upper()
        tw = d.textlength(txt, font=f)
        pad = 34
        w, h = tw + 2 * pad, f.size * 1.6
        x, y = (self.W - w) / 2, self.g.title_y - (1 - min(p, 1)) * 40
        d.rounded_rectangle([x, y, x + w, y + h], radius=h * 0.28, fill=(255, 255, 255, int(240 * min(1, p * 2))))
        d.text((x + pad, y + h * 0.18), txt, font=f, fill=(0, 0, 0, int(255 * min(1, p * 2))))

    def _stat(self, d, s, lt):
        ni = stat_index(s.words)
        if ni is None:
            return
        t0, _ = s.word_times[ni]
        tok = s.words[ni].strip(".,!?;:")
        p = (lt - t0 + 0.15) / 0.7
        if p <= 0:
            return
        shown = format_count(tok, p)
        size = int(self.g.base * 2.1)
        f = self.font(size)
        pop = spring(lt - t0 + 0.15, 300, 17)
        f = self.font(max(20, int(size * (0.7 + 0.3 * min(pop, 1.2))) // 2 * 2))
        w = d.textlength(shown, font=f)
        self._text(d, ((self.W - w) / 2, self.g.num_y - f.size / 2), shown, f, (*self.accent, 255), f.size)

    def _end_card(self, d, lt):
        label = self.handle or "FOLLOW FOR MORE"
        f = self.font(max(30, int(self.g.base * 0.42)), ui=True)
        p = spring(lt - 0.25, 240, 18)
        if p <= 0:
            return
        pulse = 1 + 0.035 * math.sin(lt * 7) * min(1, lt / 0.8)
        tw = d.textlength(label, font=f)
        w, h = (tw + 90) * pulse, f.size * 1.9 * pulse
        x, y = (self.W - w) / 2, self.g.handle_y + (1 - min(p, 1)) * 50
        a = int(255 * min(1, p * 2))
        d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=(*self.accent, a))
        d.text(((self.W - tw) / 2, y + (h - f.size * 1.2) / 2), label, font=f, fill=(0, 0, 0, a))

    def frame(self, t: float) -> Image.Image:
        si = next((i for i, s in enumerate(self.scenes) if t < s.start + s.dur), len(self.scenes) - 1)
        s = self.scenes[si]
        lt = max(0.0, t - s.start)
        v = self.videos[si]
        shakes = [s.word_times[i][0] for i in s.emph if i < len(s.word_times)]
        img = v.frame(lt, shakes) if v else Image.new("RGB", (self.W, self.H), (18, 18, 20))
        mask = self.masks["end" if s.kind == "cta" else "normal"]
        a = (np.asarray(img, dtype=np.uint16) * mask) >> 8
        img = Image.fromarray(a.astype(np.uint8))
        d = ImageDraw.Draw(img, "RGBA")
        # thin progress line along the very top
        d.rectangle([0, 0, self.W * min(1.0, t / self.total), 7], fill=(*self.accent, 230))
        self._title(d, t)
        if s.kind == "stat":
            self._stat(d, s, lt)
        self._captions(d, s, lt)
        if s.kind == "cta":
            self._end_card(d, lt)
        if si and lt < 0.07:   # two-frame flash on each cut
            d.rectangle([0, 0, self.W, self.H], fill=(255, 255, 255, int(70 * (1 - lt / 0.07))))
        return img

    def blurred(self, t: float, sub: int) -> bytes:
        return self.frame(t).tobytes()     # real footage already carries motion blur

    def close(self):
        for v in self.videos:
            if v: v.close()
