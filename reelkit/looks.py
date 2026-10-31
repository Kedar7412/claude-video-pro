"""Look presets: one name sets captions, camera, cuts, colour grade, music mood and voice together.
A creative brief picks a look and may override any field (see SKILL.md)."""
import copy

# Grades use only cheap filters: `eq` (brightness/contrast/saturation) and `lutyuv` (tint in the small chroma planes).
# `colorbalance` and `curves` looked similar but cost 5-10x more render time.
GRADES = {
    "punchy":  "eq=contrast=1.10:saturation=1.25:brightness=-0.02,vignette=angle=PI/5",
    "clean":   "eq=contrast=1.04:saturation=1.08,vignette=angle=PI/7",
    "warm":    "eq=contrast=1.03:saturation=0.98:brightness=0.01,lutyuv=u='val-4':v='val+5',vignette=angle=PI/6",
    "film":    "eq=contrast=1.12:saturation=0.88,lutyuv=u='val+3':v='val+2',vignette=angle=PI/5",
    "cold":    "eq=contrast=1.08:saturation=0.55:brightness=-0.04,lutyuv=u='val+6':v='val-4',vignette=angle=PI/4",
    "gold":    "eq=contrast=1.06:saturation=1.05,lutyuv=u='val-6':v='val+7',vignette=angle=PI/5",
    "bright":  "eq=contrast=1.06:saturation=1.30:brightness=0.02,vignette=angle=PI/8",
    "none":    "",
}

BASE = {
    "caption": {"font": "anton", "weight": None, "case": "upper", "size": 1.0, "words": 3, "chars": 16,
                "highlight": "color", "stroke": True, "pos": 0.60},
    "camera": {"amount": 1.0, "punch": 1.0, "shake": True, "exit_zoom": True},
    "cut": "flash",            # flash | zoom | fade | dip | hard
    "grade": "punchy",
    "accent": "yellow",
    "mood": "upbeat",
    "voice": "en-US-AndrewMultilingualNeural",
    "rate": "+8%",
    "pitch": "+0Hz",
}

LOOKS = {
    # fast, loud, made to stop the scroll: motivation, challenges, "X things you didn't know"
    "hype": {"caption": {"size": 1.05}, "grade": "punchy", "accent": "yellow", "mood": "hype",
             "voice": "en-US-GuyNeural", "rate": "+12%"},
    # tips, how-to, explainers: readable, confident, less shaking
    "explainer": {"caption": {"font": "montserrat", "weight": "ExtraBold", "case": "sentence", "size": 0.80,
                              "highlight": "box", "stroke": False},
                  "camera": {"amount": 0.7, "punch": 0.5, "shake": False}, "cut": "zoom", "grade": "clean",
                  "accent": "yellow", "mood": "upbeat", "voice": "en-US-AndrewMultilingualNeural", "rate": "+6%"},
    # wellness, reflection, quotes: slow, soft, serif
    "calm": {"caption": {"font": "playfair", "weight": "SemiBold", "case": "sentence", "size": 0.78, "words": 4,
                         "chars": 22, "highlight": "reveal", "stroke": False, "pos": 0.52},
             "camera": {"amount": 0.45, "punch": 0.0, "shake": False, "exit_zoom": False}, "cut": "fade",
             "grade": "warm", "accent": "white", "mood": "calm", "voice": "en-US-AvaMultilingualNeural",
             "rate": "-4%", "pitch": "-2Hz"},
    # storytime, history, case studies: cinematic, measured
    "story": {"caption": {"font": "montserrat", "weight": "Bold", "case": "sentence", "size": 0.80, "words": 4,
                          "chars": 22, "highlight": "color", "stroke": True},
              "camera": {"amount": 0.6, "punch": 0.3, "shake": False, "exit_zoom": False}, "cut": "fade",
              "grade": "film", "accent": "orange", "mood": "cinematic", "voice": "en-US-ChristopherNeural", "rate": "+2%"},
    # mystery, true crime, warnings, scary facts
    "dark": {"caption": {"size": 0.95}, "camera": {"amount": 0.6, "punch": 0.6, "shake": True, "exit_zoom": False},
             "cut": "dip", "grade": "cold", "accent": "red", "mood": "dark", "voice": "en-US-ChristopherNeural",
             "rate": "-2%", "pitch": "-4Hz"},
    # fashion, travel, premium products: minimal, elegant
    "luxury": {"caption": {"font": "playfair", "weight": "Medium", "case": "upper", "size": 0.66, "words": 3,
                           "chars": 18, "highlight": "reveal", "stroke": False, "pos": 0.56},
               "camera": {"amount": 0.4, "punch": 0.0, "shake": False, "exit_zoom": False}, "cut": "fade",
               "grade": "gold", "accent": "gold", "mood": "lofi", "voice": "en-US-AriaNeural", "rate": "-6%"},
    # comedy, memes, relatable moments: snappy and bright
    "funny": {"caption": {"size": 1.08, "words": 2, "chars": 12}, "cut": "flash", "grade": "bright", "accent": "green",
              "mood": "upbeat", "voice": "en-US-BrianMultilingualNeural", "rate": "+10%", "pitch": "+2Hz"},
}


def _merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def resolve(name="hype", overrides=None):
    """Full look dict: BASE <- preset <- brief overrides."""
    if name not in LOOKS:
        raise SystemExit(f"unknown look '{name}'; choose from {', '.join(LOOKS)}")
    look = _merge(_merge(BASE, LOOKS[name]), overrides or {})
    if look["grade"] in GRADES:
        look["grade_filter"] = GRADES[look["grade"]]
    else:
        look["grade_filter"] = look["grade"]       # a raw ffmpeg filter string is allowed too
    return look
