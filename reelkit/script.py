"""Script parsing, auto-splitting of long scenes, scene-kind detection, and topic -> script generation."""
import hashlib, json, os, re
from pathlib import Path

from .common import Scene

NUM_RE = re.compile(r"^[\$€£]?\d[\d,\.]*(?:[%xXkKmMbB]|\+)*$")


def stat_index(words):
    """Index of a number-like word (e.g. 30, $27, 200,000+, 10x) or None."""
    for i, w in enumerate(words):
        if NUM_RE.match(w.strip(".,!?;:")):
            return i
    return None


def split_long(text: str, max_words: int) -> list[str]:
    """Split a long line at the punctuation closest to its middle (else mid-word) until each part fits."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    mid = len(words) / 2
    cands = [i + 1 for i, w in enumerate(words[:-1]) if w[-1] in ",;:—-.!?" and 3 <= i + 1 <= len(words) - 3]
    cut = min(cands, key=lambda i: abs(i - mid)) if cands else round(mid)
    return split_long(" ".join(words[:cut]), max_words) + split_long(" ".join(words[cut:]), max_words)


def parse_script(raw: str, max_words: int = 14) -> list[Scene]:
    raw = raw.strip()
    blocks = [b.strip() for b in re.split(r"\n\s*\n", raw) if b.strip()]
    if len(blocks) == 1:  # no blank lines: one scene per line, else per sentence
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        blocks = lines if len(lines) > 1 else re.split(r"(?<=[.!?])\s+", raw)
    texts = []
    for b in blocks:
        texts += split_long(" ".join(b.split()), max_words)
    scenes = [Scene(text=t, words=t.split()) for t in texts]
    assign_kinds(scenes)
    return scenes


def assign_kinds(scenes: list[Scene]):
    """hook first, cta last, number scenes become 'stat' (max 2, never back to back) for layout variety."""
    stats = 0
    for i, s in enumerate(scenes):
        if i == 0:
            s.kind = "hook"
        elif i == len(scenes) - 1 and len(scenes) > 2:
            s.kind = "cta"
        elif stat_index(s.words) is not None and stats < 2 and scenes[i - 1].kind != "stat":
            s.kind = "stat"; stats += 1
        else:
            s.kind = "card"


# ───────────────────────── topic -> script ─────────────────────────
SYSTEM_PROMPT = """You write scripts for vertical short-form video (Instagram Reels / TikTok), spoken as voiceover.
Hard rules, based on how Reels perform:
- Scene 1 is the hook: at most 8 words, spoken in under 2 seconds. Use a pattern interrupt, a curiosity gap, a bold claim or a
  specific number. Never start with "Hey guys", a greeting, or setup/context.
- One idea per scene. Each scene is ONE short sentence of at most 12 words, written for the ear (contractions, no jargon).
- Include exactly one concrete number or fact as its own scene (digits, e.g. "It takes 30 days.").
- Every scene must teach, prove or advance the story. No filler, no recap of the hook.
- The last scene is a call to action that gives one reason to act (save, follow, comment a keyword), and where possible echoes the hook so the reel loops.
- Total spoken length: roughly {words} words ({seconds} seconds). {n} scenes, plus or minus one.
- Tone: {tone}. Language: {lang}. Do not make claims you cannot support; no fake statistics or testimonials.
Also write the post caption: line 1 repeats the hook (it is the only line visible before "more"), 1-2 lines of extra value,
then one CTA line. And 3-5 specific, relevant hashtags (not generic ones like #fyp).
For each scene also pick ONE illustration for the on-screen prop, from exactly this list, or "" when none fits: {props}.
Return ONLY JSON: {{"scenes": ["..."], "props": ["clock", "", "..."], "caption": "...", "hashtags": ["word", "..."]}}"""


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("LLM returned no JSON")
    data = json.loads(m.group(0))
    scenes = [" ".join(str(s).split()) for s in data.get("scenes", []) if str(s).strip()]
    if len(scenes) < 3:
        raise ValueError("LLM returned fewer than 3 scenes")
    props = [str(x).strip().lower() for x in data.get("props", [])]
    return {"scenes": scenes, "props": props, "caption": str(data.get("caption", "")).strip(),
            "hashtags": [str(h).lstrip("#").strip() for h in data.get("hashtags", []) if str(h).strip()][:5]}


def _llm(system: str, user: str) -> str:
    import requests
    model = os.environ.get("REEL_LLM_MODEL")
    if os.environ.get("ANTHROPIC_API_KEY"):
        h = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
        if not model:  # resolve a current model at runtime instead of hard-coding an id that may be retired
            ms = requests.get("https://api.anthropic.com/v1/models", headers=h, timeout=30).json().get("data", [])
            ids = [m["id"] for m in ms]
            model = next((i for i in ids if "sonnet" in i), ids[0] if ids else None)
            if not model:
                raise RuntimeError("could not list Anthropic models; set REEL_LLM_MODEL")
        r = requests.post("https://api.anthropic.com/v1/messages", headers=h, timeout=120,
                          json={"model": model, "max_tokens": 1500, "system": system,
                                "messages": [{"role": "user", "content": user}]})
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if os.environ.get("OPENAI_API_KEY"):
        r = requests.post("https://api.openai.com/v1/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                          json={"model": model or "gpt-4o-mini", "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("no ANTHROPIC_API_KEY or OPENAI_API_KEY set")


HOOKS = [
    "Nobody tells you this about {t}.",
    "Stop doing {t} the hard way.",
    "{t}: the part everyone skips.",
    "You're doing {t} backwards.",
    "Here's what {t} really takes.",
]


def offline_script(topic: str, points: list[str], cta: str | None) -> dict:
    """No LLM available: build a script from the user's own bullet points (hook formula + points + CTA)."""
    pick = int(hashlib.sha1(topic.encode()).hexdigest(), 16) % len(HOOKS)
    scenes = [HOOKS[pick].format(t=topic)] + [p.strip().rstrip(".") + "." for p in points if p.strip()]
    scenes.append(cta or f"Save this, and follow for more on {topic}.")
    tags = [re.sub(r"\W", "", w.title()) for w in topic.split()[:3] if len(w) > 2]
    props = [str(x).strip().lower() for x in data.get("props", [])]
    return {"scenes": scenes, "props": props, "caption": f"{scenes[0]}\n\n{scenes[-1]}", "hashtags": [t for t in tags if t][:5]}


def generate(topic: str, points: list[str], n_scenes=7, seconds=30, lang="English", tone="direct, warm, confident",
             cta=None) -> dict:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        from .figures import PROPS
        sysmsg = SYSTEM_PROMPT.format(words=int(seconds * 2.7), seconds=seconds, n=n_scenes, tone=tone, lang=lang,
                                      props=", ".join(PROPS))
        user = f"Topic: {topic}\n" + (f"Cover these points: {'; '.join(points)}\n" if points else "") + \
               (f"Call to action: {cta}\n" if cta else "")
        last = None
        for _ in range(2):
            try:
                return _extract_json(_llm(sysmsg, user))
            except Exception as e:  # retry once on malformed output
                last = e
        raise RuntimeError(f"script generation failed: {last}")
    if points:
        return offline_script(topic, points, cta)
    raise SystemExit("--topic needs an LLM key (ANTHROPIC_API_KEY or OPENAI_API_KEY), or pass your own "
                     "--points \"point one;point two;point three\", or write the script file yourself.")
