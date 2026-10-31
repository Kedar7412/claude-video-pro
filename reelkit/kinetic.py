"""Footage style: full-screen b-roll with a moving camera and kinetic captions, styled by a look (see looks.py).

Caption highlight modes: color (spoken word in the accent), box (accent box behind the spoken word),
reveal (words appear as they are spoken). Cuts: flash, zoom, fade, dip, hard. Every frame is a function of time."""
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .footage import SceneVideo, spring
from .looks import resolve
from .render import format_count, load_font
from .script import stat_index

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_FILES = {"anton": "Anton-Regular.ttf", "montserrat": "Montserrat[wght].ttf", "playfair": "PlayfairDisplay[wght].ttf"}
ACCENTS = {"yellow": (255, 214, 10), "green": (92, 255, 122), "orange": (255, 140, 50), "pink": (255, 92, 170),
           "cyan": (64, 224, 255), "red": (235, 45, 45), "white": (255, 255, 255), "gold": (232, 196, 120)}
WHITE, BLACK = (255, 255, 255), (0, 0, 0)
PUNCT = "’‘“”–—…"


def _font(path, size, variation=None):
    f = ImageFont.truetype(str(path), size)
    if variation:
        try: f.set_variation_by_name(variation)
        except Exception: pass
    return f


def _script_ok(text, family):
    """Can this bundled family draw the text? Anton/Playfair: Latin (+Vietnamese); Montserrat adds Cyrillic."""
    for c in text:
        o = ord(c)
        if o < 0x250 or c in PUNCT or 0x1E00 <= o < 0x1F00:
            continue
        if family == "montserrat" and 0x400 <= o < 0x530:
            continue
        return False
    return True


def pick_fonts(texts, family="anton", weight=None, override=None):
    """(caption font loader, UI font loader), falling back when the text needs glyphs the family lacks."""
    allt = " ".join(texts)
    mont = FONTS / FONT_FILES["montserrat"]
    if override:
        f = lambda n: load_font(n, override)
        return f, f
    for fam in (family, "montserrat"):
        path = FONTS / FONT_FILES.get(fam, "")
        if path.is_file() and _script_ok(allt, fam):
            w = weight or ("Black" if fam == "montserrat" else None)
            cap = lambda n, p=path, w=w: _font(p, n, w)
            ui = (lambda n: _font(mont, n, "ExtraBold")) if _script_ok(allt, "montserrat") else cap
            return cap, ui
    f = lambda n: load_font(n, None)
    return f, f


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
    def __init__(self, W, H, pos=0.60):
        r = W / H
        if r > 1.2:   self.cap_y, self.title_y, self.mx, self.num_y, self.base = H * 0.72, 60, 140, H * 0.40, 130
        elif r > 0.9: self.cap_y, self.title_y, self.mx, self.num_y, self.base = H * 0.66, 70, 80, H * 0.38, 120
        elif r > 0.7: self.cap_y, self.title_y, self.mx, self.num_y, self.base = H * 0.64, 100, 80, H * 0.38, 135
        else:         self.cap_y, self.title_y, self.mx, self.num_y, self.base = H * 0.60, 250, 90, H * 0.38, 150
        self.cap_y += (pos - 0.60) * H          # a look can move captions up or down from the format default
        self.handle_y = self.cap_y + self.base * 1.6


def _case(w, mode):
    return w.upper() if mode == "upper" else w


class FootageRenderer:
    def __init__(self, scenes, clips, size, handle="", title="", accent=None, font_path=None, look=None):
        self.look = look if isinstance(look, dict) else resolve(look or "hype")
        cap = self.look["caption"]
        self.scenes, self.handle, self.title = scenes, handle, (title or "").strip()
        self.W, self.H = size
        self.g = Geo(*size, pos=cap.get("pos", 0.60))
        acc = accent or self.look.get("accent", "yellow")
        self.accent = ACCENTS.get(acc, ACCENTS["yellow"]) if isinstance(acc, str) else tuple(acc)
        self.case, self.hl, self.stroke = cap.get("case", "upper"), cap.get("highlight", "color"), cap.get("stroke", True)
        self.capf, self.uif = pick_fonts([s.text for s in scenes] + [self.title, handle], cap.get("font", "anton"),
                                         cap.get("weight"), font_path)
        self._fc = {}
        self.cut = self.look.get("cut", "flash")
        self.videos = [SceneVideo(c, self.W, self.H, s.dur + (0.5 if self.cut == "fade" else 0), i,
                                  self.look.get("grade_filter", ""), self.look.get("camera"))
                       if c else None for i, (s, c) in enumerate(zip(scenes, clips))]
        for v, s in zip(self.videos, scenes):
            if v: v.dur = s.dur            # camera timing follows the scene, decoding runs a little longer for fades
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
        cap = self.look["caption"]
        out = []
        max_w = self.W - 2 * self.g.mx
        for idx in chunk_scene(s, cap.get("words", 3), cap.get("chars", 16)):
            words = [_case(s.words[i], self.case) for i in idx]
            solo = len(idx) == 1 and idx[0] in s.emph
            size = int(self.g.base * cap.get("size", 1.0) * (1.45 if solo else 1.0) * (1.12 if s.kind == "hook" else 1.0))
            lines = [list(range(len(words)))]
            while size > 40:
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
            out.append({"idx": idx, "words": words, "size": size, "lines": lines, "start": s.word_times[idx[0]][0], "solo": solo})
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
        depth = 0.42 if self.stroke else 0.55       # no outline: darken more behind the text
        band = 1 - depth * np.exp(-((y - self.g.cap_y) / (H * 0.17)) ** 2)
        if self.title:
            band *= 1 - 0.30 * np.exp(-((y - self.g.title_y) / (H * 0.12)) ** 2)
        return {"normal": (band * 256).astype(np.uint16)[:, None, None],
                "end": (band * 0.62 * 256).astype(np.uint16)[:, None, None]}

    # ── drawing ──
    def _text(self, d, xy, txt, f, fill, size):
        x, y = xy
        if self.stroke:
            sw = max(5, size // 13)
            d.text((x, y + size * 0.07), txt, font=f, fill=(0, 0, 0, 120), stroke_width=sw, stroke_fill=(0, 0, 0, 120))
            d.text((x, y), txt, font=f, fill=fill, stroke_width=sw, stroke_fill=BLACK)
        else:   # soft drop shadow only, for elegant looks
            for dx, dy, a in ((0, 4, 110), (0, 2, 140)):
                d.text((x + dx, y + dy), txt, font=f, fill=(0, 0, 0, a))
            d.text((x, y), txt, font=f, fill=fill)

    def _captions(self, d, s, si, lt):
        ch = next((c for c in self.chunks[si] if c["start"] - 0.03 <= lt < c["end"]), None)
        if ch is None:
            return
        soft = self.hl == "reveal"
        if soft:
            pop = min(1.0, (lt - ch["start"] + 0.03) / 0.25); scale = 0.96 + 0.04 * pop
        elif ch["solo"]:
            pop = spring(lt - ch["start"] + 0.03, 380, 18); scale = 0.62 + 0.38 * pop
        else:
            pop = spring(lt - ch["start"] + 0.03, 520, 26); scale = 0.80 + 0.20 * pop
        size = max(20, int(ch["size"] * scale) // 2 * 2)
        f = self.font(size)
        lh = size * (1.08 if self.case == "upper" else 1.18)
        y = self.g.cap_y - len(ch["lines"]) * lh / 2 + (1 - min(pop, 1)) * (10 if soft else 26)
        sp = d.textlength(" ", font=f)
        spoken = [gi for gi in ch["idx"] if s.word_times[gi][0] - 0.02 <= lt]
        cur = spoken[-1] if spoken else None          # exactly one word lights up: the one being said now
        for line in ch["lines"]:
            ws = [ch["words"][k] for k in line]
            widths = [d.textlength(w, font=f) for w in ws]
            x = (self.W - (sum(widths) + sp * (len(ws) - 1))) / 2
            for k, w, wd in zip(line, ws, widths):
                gi = ch["idx"][k]
                if self.hl == "box" and gi == cur:
                    pad = size * 0.12
                    d.rounded_rectangle([x - pad, y - pad * 0.2, x + wd + pad, y + size * 1.12], radius=size * 0.16,
                                        fill=(*self.accent, 255))
                    d.text((x, y), w, font=f, fill=(*BLACK, 255))
                elif self.hl == "reveal":
                    t0 = s.word_times[gi][0]
                    a = max(0.0, min(1.0, (lt - t0 + 0.05) / 0.18))
                    if a > 0:
                        col = self.accent if gi in s.emph else WHITE
                        self._text(d, (x, y + (1 - a) * 8), w, f, (*col, int(255 * a)), size)
                else:
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
        pop = spring(lt - t0 + 0.15, 300, 17)
        f = self.font(max(20, int(self.g.base * 2.1 * self.look["caption"].get("size", 1.0) * (0.7 + 0.3 * min(pop, 1.2))) // 2 * 2))
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

    def _bg(self, si, lt):
        s, v = self.scenes[si], self.videos[si]
        shakes = [s.word_times[i][0] for i in s.emph if i < len(s.word_times)]
        img = v.frame(lt, shakes) if v else Image.new("RGB", (self.W, self.H), (18, 18, 20))
        mask = self.masks["end" if s.kind == "cta" else "normal"]
        return Image.fromarray(((np.asarray(img, dtype=np.uint16) * mask) >> 8).astype(np.uint8))

    def frame(self, t: float) -> Image.Image:
        si = next((i for i, s in enumerate(self.scenes) if t < s.start + s.dur), len(self.scenes) - 1)
        s = self.scenes[si]
        lt = max(0.0, t - s.start)
        img = self._bg(si, lt)
        if si and self.cut == "fade" and lt < 0.35:            # crossfade from the previous shot
            prev = self._bg(si - 1, self.scenes[si - 1].dur + lt)
            img = Image.blend(prev, img, lt / 0.35)
        d = ImageDraw.Draw(img, "RGBA")
        d.rectangle([0, 0, self.W * min(1.0, t / self.total), 7], fill=(*self.accent, 230))
        self._title(d, t)
        if s.kind == "stat":
            self._stat(d, s, lt)
        self._captions(d, s, si, lt)
        if s.kind == "cta":
            self._end_card(d, lt)
        if si and self.cut == "flash" and lt < 0.07:
            d.rectangle([0, 0, self.W, self.H], fill=(255, 255, 255, int(70 * (1 - lt / 0.07))))
        if self.cut == "dip":                                   # brief dip to black around each cut
            tail = s.dur - lt
            a = max(0.0, 1 - lt / 0.18) if si else 0.0
            if si < len(self.scenes) - 1: a = max(a, 1 - tail / 0.12)
            if a > 0: d.rectangle([0, 0, self.W, self.H], fill=(0, 0, 0, int(255 * min(a, 1) * 0.9)))
        return img

    def blurred(self, t: float, sub: int) -> bytes:
        return self.frame(t).tobytes()     # real footage already carries motion blur

    def close(self):
        for v in self.videos:
            if v: v.close()
