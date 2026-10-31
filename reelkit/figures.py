"""Cut-paper figures: a lip-synced host and a library of props chosen from the script's own words.

Everything is drawn procedurally (supersampled) in a flat 'cut paper' style with an offset shadow.
Props are matched to scenes by keyword (or by names the LLM returns, validated against this library).
"""
import math, re
from functools import lru_cache
from PIL import Image, ImageChops, ImageDraw, ImageFont

SS = 2           # supersampling for the host layer
IC = 400         # icon canvas size
PAPER = (255, 252, 246)
SHADOW = (0, 0, 0, 55)

PROP_KEYWORDS = {
    "clock":  "time hour hours minute minutes second seconds clock week daily schedule deadline early late wait",
    "bulb":   "idea ideas tip tips trick hack think thought smart insight learn clever",
    "phone":  "phone app apps social post posts scroll instagram tiktok notification text mobile screen",
    "drop":   "water shower cold drink rain sweat hydrate wash wet ice",
    "heart":  "love health healthy heart care kind friend friends like feel",
    "star":   "best top favorite favourite quality rated win great free star",
    "check":  "done step steps rule rules checklist correct proven works simple easy start habit",
    "chart":  "grow growth increase results result percent data metrics rise stats views sales improve progress",
    "coin":   "money cash price save saving cost budget invest pay earn dollar rich cheap",
    "moon":   "sleep night bed rest dream tired evening nap",
    "sun":    "morning energy sun bright summer light vitamin wake",
    "rocket": "launch speed boost startup ship fast faster quick",
    "target": "goal goals focus aim target mission plan precise",
    "book":   "book books read reading study lesson course school guide story",
    "fire":   "hot streak trending viral burn calories intense hard fire",
    "camera": "video film record camera shoot content creator edit reel reels",
    "lock":   "password secure security private safe protect lock",
    "mail":   "email mail inbox newsletter message send subscribe",
}
PROPS = list(PROP_KEYWORDS)


def assign_props(scenes, llm_props=None):
    """Pick a prop per scene from its words. LLM-suggested names win if valid. No match -> no prop (never random)."""
    prev = None
    used = {}
    for i, s in enumerate(scenes):
        s.prop = None
        if s.kind == "cta":
            continue
        if llm_props and i < len(llm_props) and llm_props[i] in PROPS:
            s.prop = llm_props[i]
        else:
            toks = [re.sub(r"\W", "", w.lower()) for w in s.words]
            best, score = None, 0
            for name, kws in PROP_KEYWORDS.items():
                sc = sum(1 for t in toks if t in kws.split())
                if name == prev: sc -= 0.5
                if used.get(name, 0) >= 2: sc -= 0.5
                if sc > score: best, score = name, sc
            s.prop = best
        if s.prop:
            prev = s.prop; used[s.prop] = used.get(s.prop, 0) + 1


# ───────────────────────── props ─────────────────────────
def _shadowed(draw_fn):
    """Render draw_fn twice: dark offset copy first, then the real thing (cut-paper depth)."""
    def make(pal, font_fn):
        S = IC * SS
        out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        dsh = ImageDraw.Draw(sh); dsh._img = sh
        draw_fn(dsh, pal, font_fn, shadow=True)
        a = sh.split()[3].point(lambda v: 55 if v else 0)
        ox, oy = 10 * SS, 14 * SS
        out.paste((0, 0, 0, 255), (ox, oy, ox + S, oy + S), a)
        dout = ImageDraw.Draw(out); dout._img = out
        draw_fn(dout, pal, font_fn, shadow=False)
        return out.resize((IC, IC), Image.LANCZOS)
    return make


def _c(d, x, y, r, **kw): d.ellipse([x * SS - r * SS, y * SS - r * SS, x * SS + r * SS, y * SS + r * SS], **kw)
def _p(d, pts, **kw): d.polygon([(x * SS, y * SS) for x, y in pts], **kw)
def _r(d, x0, y0, x1, y1, rad=0, **kw): d.rounded_rectangle([x0 * SS, y0 * SS, x1 * SS, y1 * SS], radius=rad * SS, **kw)
def _l(d, pts, w, **kw): d.line([(x * SS, y * SS) for x, y in pts], width=w * SS, joint="curve", **kw)


def _clock(d, P, f, shadow):
    _c(d, 200, 215, 150, fill=PAPER, outline=P["dark"], width=14 * SS)
    _c(d, 95, 85, 38, fill=P["acc"]); _c(d, 305, 85, 38, fill=P["acc"])
    _l(d, [(200, 215), (200, 120)], 14, fill=P["dark"]); _l(d, [(200, 215), (262, 245)], 14, fill=P["acc"])
    _c(d, 200, 215, 14, fill=P["dark"])
def _bulb(d, P, f, shadow):
    for a in range(-60, 61, 30):
        x, y = math.sin(math.radians(a)), -math.cos(math.radians(a))
        _l(d, [(200 + x * 135, 150 + y * 135), (200 + x * 175, 150 + y * 175)], 12, fill=P["acc"])
    _c(d, 200, 160, 100, fill=P["acc"]); _r(d, 150, 245, 250, 330, 18, fill=P["dark"])
    _l(d, [(160, 285), (240, 285)], 8, fill=PAPER); _c(d, 165, 125, 22, fill=(255, 255, 255, 120))
def _phone(d, P, f, shadow):
    _r(d, 110, 25, 290, 375, 40, fill=P["dark"]); _r(d, 128, 75, 272, 325, 14, fill=PAPER)
    _r(d, 145, 100, 255, 150, 12, fill=P["acc"]); _r(d, 145, 170, 230, 190, 8, fill=(0, 0, 0, 40)); _r(d, 145, 205, 255, 225, 8, fill=(0, 0, 0, 40))
    _c(d, 200, 352, 11, fill=PAPER)
def _drop(d, P, f, shadow):
    _p(d, [(200, 30), (112, 225), (288, 225)], fill=P["acc"]); _c(d, 200, 250, 100, fill=P["acc"])
    _c(d, 160, 262, 20, fill=(255, 255, 255, 140))
def _heart(d, P, f, shadow):
    _c(d, 140, 150, 80, fill=P["acc"]); _c(d, 260, 150, 80, fill=P["acc"]); _p(d, [(66, 185), (334, 185), (200, 350)], fill=P["acc"])
    _c(d, 112, 120, 18, fill=(255, 255, 255, 140))
def _star(d, P, f, shadow):
    pts = []
    for i in range(10):
        r = 160 if i % 2 == 0 else 70; a = math.pi / 2 + i * math.pi / 5
        pts.append((200 + r * math.cos(a), 210 - r * math.sin(a)))
    _p(d, pts, fill=P["acc"], outline=P["dark"], width=8 * SS)
def _check(d, P, f, shadow):
    _c(d, 200, 200, 150, fill=P["acc"]); _l(d, [(125, 205), (180, 262), (285, 145)], 36, fill=PAPER)
def _chart(d, P, f, shadow):
    _r(d, 60, 235, 135, 350, 8, fill=P["dark"]); _r(d, 160, 165, 235, 350, 8, fill=P["acc"]); _r(d, 260, 95, 335, 350, 8, fill=P["dark"])
    _l(d, [(55, 200), (150, 130), (215, 150), (330, 40)], 12, fill=P["acc"]); _p(d, [(345, 25), (300, 40), (332, 78)], fill=P["acc"])
def _coin(d, P, f, shadow):
    _c(d, 200, 200, 150, fill=P["acc"], outline=P["dark"], width=12 * SS); _c(d, 200, 200, 108, outline=P["dark"], width=7 * SS)
    ft = f(190); d.text((200 * SS, 205 * SS), "$", font=ft, fill=P["dark"], anchor="mm")
def _moon(d, P, f, shadow):
    S = IC * SS
    m = Image.new("L", (S, S), 0); md = ImageDraw.Draw(m)
    md.ellipse([60 * SS, 60 * SS, 340 * SS, 340 * SS], fill=255); md.ellipse([140 * SS, 20 * SS, 400 * SS, 280 * SS], fill=0)
    d._img.paste(P["acc"], (0, 0), m)
    for x, y, r in ((300, 290, 12), (330, 200, 8), (255, 330, 7)): _c(d, x, y, r, fill=PAPER)
def _sun(d, P, f, shadow):
    for k in range(12):
        a = k * math.pi / 6
        _l(d, [(200 + math.cos(a) * 105, 200 + math.sin(a) * 105), (200 + math.cos(a) * 165, 200 + math.sin(a) * 165)], 16, fill=P["acc"])
    _c(d, 200, 200, 85, fill=P["acc"]); _c(d, 200, 200, 60, fill=(255, 255, 255, 70))
def _rocket(d, P, f, shadow):
    _p(d, [(110, 300), (160, 210), (160, 290)], fill=P["acc"]); _p(d, [(290, 300), (240, 210), (240, 290)], fill=P["acc"])
    _p(d, [(165, 285), (235, 285), (200, 380)], fill=P["acc"])
    _p(d, [(200, 20), (262, 120), (262, 290), (138, 290), (138, 120)], fill=PAPER, outline=P["dark"], width=8 * SS)
    _p(d, [(200, 20), (255, 112), (145, 112)], fill=P["acc"]); _c(d, 200, 190, 36, fill=P["dark"]); _c(d, 200, 190, 22, fill=(150, 210, 255))
def _target(d, P, f, shadow):
    for r, c in ((150, P["dark"]), (115, PAPER), (80, P["acc"]), (45, PAPER), (18, P["acc"])): _c(d, 200, 200, r, fill=c)
    _l(d, [(200, 200), (330, 70)], 12, fill=P["dark"]); _p(d, [(330, 70), (350, 30), (370, 50)], fill=P["acc"]); _p(d, [(330, 70), (370, 50), (360, 90)], fill=P["acc"])
def _book(d, P, f, shadow):
    _p(d, [(200, 90), (50, 70), (50, 300), (200, 325)], fill=PAPER, outline=P["dark"], width=8 * SS)
    _p(d, [(200, 90), (350, 70), (350, 300), (200, 325)], fill=PAPER, outline=P["dark"], width=8 * SS)
    for y in (130, 170, 210, 250):
        _l(d, [(78, y - 5), (172, y + 8)], 8, fill=P["acc"] if y == 130 else (0, 0, 0, 60)); _l(d, [(228, y + 8), (322, y - 5)], 8, fill=(0, 0, 0, 60))
def _fire(d, P, f, shadow):
    _p(d, [(200, 20), (270, 120), (320, 220), (290, 320), (200, 375), (110, 320), (80, 220), (130, 140), (150, 190), (180, 110)], fill=P["acc"])
    _p(d, [(200, 170), (245, 240), (255, 310), (200, 350), (145, 310), (155, 240)], fill=(255, 226, 120))
def _camera(d, P, f, shadow):
    _r(d, 40, 100, 360, 330, 36, fill=P["dark"]); _r(d, 90, 70, 190, 115, 14, fill=P["dark"])
    _c(d, 200, 220, 78, fill=PAPER); _c(d, 200, 220, 52, fill=P["acc"]); _c(d, 183, 203, 14, fill=(255, 255, 255, 150)); _c(d, 320, 150, 14, fill=P["acc"])
def _lock(d, P, f, shadow):
    d.arc([115 * SS, 30 * SS, 285 * SS, 230 * SS], 180, 360, fill=P["dark"], width=34 * SS)
    _l(d, [(132, 130), (132, 190)], 34, fill=P["dark"]); _l(d, [(268, 130), (268, 190)], 34, fill=P["dark"])
    _r(d, 80, 180, 320, 365, 34, fill=P["acc"]); _c(d, 200, 255, 28, fill=P["dark"]); _r(d, 190, 255, 210, 315, 8, fill=P["dark"])
def _mail(d, P, f, shadow):
    _r(d, 40, 85, 360, 315, 22, fill=PAPER, outline=P["dark"], width=10 * SS)
    _l(d, [(50, 100), (200, 225), (350, 100)], 12, fill=P["dark"]); _c(d, 330, 90, 34, fill=P["acc"])


_ICONS = {k: _shadowed(v) for k, v in {
    "clock": _clock, "bulb": _bulb, "phone": _phone, "drop": _drop, "heart": _heart, "star": _star, "check": _check,
    "chart": _chart, "coin": _coin, "moon": _moon, "sun": _sun, "rocket": _rocket, "target": _target, "book": _book,
    "fire": _fire, "camera": _camera, "lock": _lock, "mail": _mail}.items()}


def make_prop(name, accent, dark, font_fn) -> Image.Image:
    return _ICONS[name]({"acc": accent, "dark": dark}, font_fn)


# ───────────────────────── host ─────────────────────────
SKIN = (238, 190, 152)
SKIN_D = (214, 162, 126)
HAIR = (58, 40, 34)
MOUTH = (140, 38, 48)
HOST_W, HOST_H = 420, 470   # unscaled canvas


def _hp(d, pts, **kw): d.polygon([(x * SS, y * SS) for x, y in pts], **kw)
def _he(d, cx, cy, rx, ry, **kw): d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], **kw)
def _hl(d, pts, w, **kw): d.line([(x * SS, y * SS) for x, y in pts], width=int(w * SS), joint="curve", **kw)


def _host_parts(d, accent, dark, t, amp, emph, photo):
    cx, by = HOST_W / 2, HOST_H - 20
    bob = 5 * math.sin(t * 2 * math.pi * 1.1) + 12 * emph
    by -= bob
    # arms (behind body edge): rear arm rests, front arm gestures on emphasis
    ang = 0.15 + 1.1 * emph
    sh = (cx + 100, by - 135)
    el = (sh[0] + 52, sh[1] + 70 - 40 * emph)
    hand = (el[0] + 20 + 20 * emph, el[1] + 62 - 105 * emph)
    _hl(d, [sh, el, hand], 40, fill=accent); _he(d, hand[0], hand[1], 26, 26, fill=SKIN)
    _hl(d, [(cx - 100, by - 135), (cx - 150, by - 55), (cx - 140, by + 8)], 40, fill=accent); _he(d, cx - 140, by + 8, 24, 24, fill=SKIN)
    # body
    _hp(d, [(cx - 135, by + 30), (cx - 110, by - 125), (cx - 62, by - 160), (cx + 62, by - 160), (cx + 110, by - 125), (cx + 135, by + 30)], fill=accent)
    _hp(d, [(cx - 34, by - 160), (cx, by - 112), (cx + 34, by - 160)], fill=PAPER)
    _he(d, cx, by - 172, 28, 22, fill=SKIN_D)
    # head
    hy = by - 268
    if photo is None:
        _he(d, cx, hy - 14, 104, 96, fill=HAIR)            # back hair
        _he(d, cx, hy, 90, 100, fill=SKIN)
        _hp(d, [(cx - 92, hy - 20), (cx - 70, hy - 82), (cx - 10, hy - 104), (cx + 70, hy - 84), (cx + 92, hy - 22),
                (cx + 62, hy - 52), (cx + 8, hy - 62), (cx - 52, hy - 48)], fill=HAIR)   # fringe
        blink = 0.1 if (t % 3.4) < 0.12 else 1.0
        for ex in (-34, 34):
            _he(d, cx + ex, hy + 2, 10, 12 * blink, fill=dark)
            if blink > 0.5: _he(d, cx + ex + 3, hy - 2, 3, 3, fill=PAPER)
            _hl(d, [(cx + ex - 16, hy - 26 - 8 * emph), (cx + ex + 16, hy - 28 - 5 * emph)], 6, fill=HAIR)
        _he(d, cx - 56, hy + 36, 16, 11, fill=(236, 120, 112, 110)); _he(d, cx + 56, hy + 36, 16, 11, fill=(236, 120, 112, 110))
        open_ = min(1.0, amp * 1.4)
        if open_ < 0.08:
            d.arc([(cx - 26) * SS, (hy + 30) * SS, (cx + 26) * SS, (hy + 62) * SS], 20, 160, fill=MOUTH, width=6 * SS)
        else:
            _he(d, cx, hy + 48, 22 + 6 * open_, 4 + 24 * open_, fill=MOUTH)
            if open_ > 0.35: _he(d, cx, hy + 48 + 10 * open_, 12, 6 + 5 * open_, fill=(210, 90, 100))
    else:
        r = 104
        _he(d, cx, hy, r + 10, r + 10, fill=PAPER)
        m = Image.new("L", (2 * r * SS, 2 * r * SS), 0); ImageDraw.Draw(m).ellipse([0, 0, 2 * r * SS - 1, 2 * r * SS - 1], fill=255)
        ph = photo.resize((2 * r * SS, 2 * r * SS), Image.LANCZOS)
        d._img.paste(ph, (int((cx - r) * SS), int((hy - r) * SS)), m)


def make_host_layer(accent, dark, t, amp, emph, photo=None) -> Image.Image:
    """RGBA host at HOST_W x HOST_H (supersampled then reduced)."""
    S = (HOST_W * SS, HOST_H * SS)
    body = Image.new("RGBA", S, (0, 0, 0, 0))
    db = ImageDraw.Draw(body); db._img = body
    _host_parts(db, accent, dark, t, amp, emph, photo)
    sh = Image.new("RGBA", S, (0, 0, 0, 0))
    ox, oy = 10 * SS, 14 * SS
    sh.paste((0, 0, 0, 255), (ox, oy, ox + S[0], oy + S[1]), body.split()[3].point(lambda v: 60 if v else 0))
    out = Image.alpha_composite(sh, body)
    return out.resize((HOST_W, HOST_H), Image.LANCZOS)
