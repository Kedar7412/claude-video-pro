"""Quality gates run before the final render. Hard failures stop the run; warnings are reported.

Two families: craft (pace, hook, readability, length) and originality (heuristics for generic, repetitive or
already-published scripts). Originality checks are heuristics: they catch the common ways reels end up samey,
they cannot prove a script is novel."""
import difflib, json, re, time
from pathlib import Path

BAD_OPENERS = ["hey guys", "hi guys", "hello everyone", "welcome back", "in this video", "today i'm going to",
               "today we", "what's up", "let me tell you", "before we start", "don't forget to like"]
SOFT_OPENERS = ["did you know", "are you tired of", "have you ever wondered", "imagine if"]
HYPE = ["amazing", "incredible", "game-changer", "game changer", "revolutionary", "unlock", "ultimate", "mind-blowing",
        "literally", "insane", "crazy", "secret", "life-changing", "hack"]


def _norm_words(text): return re.findall(r"[a-z0-9']+", text.lower())
def _shingles(words, n=3): return {tuple(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def load_history(path):
    try: return json.loads(Path(path).read_text())
    except Exception: return []


def save_history(path, scenes, title=""):
    h = [x for x in load_history(path) if not (title and x.get("title") == title)]   # a re-render replaces its own entry
    h.append({"ts": time.strftime("%Y-%m-%d"), "title": title, "text": " ".join(s.text for s in scenes)})
    Path(path).write_text(json.dumps(h[-200:], indent=1))


def originality(scenes, history, title=""):
    history = [h for h in history if not (title and h.get("title") == title)]   # re-rendering the same script is a revision
    hard, warn, info = [], [], {}
    texts = [s.text for s in scenes]
    low0 = texts[0].lower()
    for o in BAD_OPENERS:
        if low0.startswith(o) or o in low0[:40]:
            hard.append(f"hook starts with a cliché setup ('{o}'); open with the payoff instead"); break
    for o in SOFT_OPENERS:
        if low0.startswith(o): warn.append(f"hook opens with the very common '{o}...'; a specific claim or number usually beats it")
    # hype / filler density
    allw = _norm_words(" ".join(texts))
    hyp = [h for h in HYPE if h in " ".join(texts).lower()]
    info["hype_words"] = hyp
    if len(hyp) >= 3 or (allw and sum(" ".join(texts).lower().count(h) for h in hyp) / len(allw) > 0.08):
        warn.append(f"hype words ({', '.join(hyp)}) replace specifics; swap them for a concrete detail")
    # repetition inside the script
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            r = difflib.SequenceMatcher(None, texts[i].lower(), texts[j].lower()).ratio()
            if r > 0.78: hard.append(f"scenes {i + 1} and {j + 1} say nearly the same thing ({r:.0%})")
    # specificity: a number or a proper noun somewhere
    def specific(t):
        ws = t.split()
        return bool(re.search(r"\d", t)) or any(w[:1].isupper() and len(w) > 2 and ws[i - 1][-1] not in ".!?" and w != "I"
                                                 for i, w in enumerate(ws) if i > 0)
    spec = any(specific(t) for t in texts)
    info["has_specific_detail"] = spec
    if not spec: warn.append("no number, name or concrete detail anywhere; generic scripts blend in")
    # visual sameness
    for i in range(1, len(scenes)):
        a, b = scenes[i - 1], scenes[i]
        if a.kind == b.kind and a.prop and a.prop == b.prop:
            warn.append(f"scenes {i} and {i + 1} look the same (same layout and prop)")
    # already-made scripts
    me = _shingles(allw)
    best, when = 0.0, ""
    for h in history:
        other = _shingles(_norm_words(h["text"]))
        sim = len(me & other) / max(1, len(me | other))
        if sim > best: best, when = sim, f"{h.get('ts', '?')} {h.get('title', '')}".strip()
    info["max_similarity_to_past_reels"] = round(best, 2)
    if best > 0.7: hard.append(f"this script is {best:.0%} identical to a reel you already made ({when})")
    elif best > 0.4: warn.append(f"this script overlaps {best:.0%} with an earlier reel ({when})")
    return hard, warn, info


def run_gates(scenes, renderer, total, max_seconds):
    hard, warn, info = [], [], {}
    # PACE: something new must appear on screen regularly (cut or a word landing)
    # events: cuts, word onsets, and the end of each spoken word (its highlight/underline is still moving until then)
    ev = sorted({0.0, total} | {s.start for s in scenes} | {s.start + a for s in scenes for a, _ in s.word_times}
                | {s.start + b + 0.08 for s in scenes for _, b in s.word_times})
    gaps = [(b - a, a) for a, b in zip(ev, ev[1:])]
    worst, at = max(gaps)
    info["max_flat_stretch_s"] = round(worst, 2)
    if worst > 1.5: hard.append(f"pace: {worst:.1f}s with nothing new at {at:.1f}s (limit 1.5s)")
    elif worst > 1.2: warn.append(f"pace: {worst:.1f}s flat stretch at {at:.1f}s")
    # HOOK
    hook = scenes[0]
    info["hook_first_word_s"] = round(hook.word_times[0][0], 2)
    if len(hook.words) > 10: hard.append(f"hook has {len(hook.words)} words (limit 10)")
    if hook.word_times[0][0] > 0.6: hard.append(f"hook's first word lands at {hook.word_times[0][0]:.2f}s (limit 0.6s)")
    if hook.speech > 3.0: warn.append(f"hook takes {hook.speech:.1f}s to say; aim for under 2s")
    # SCENE LENGTH / RATE
    for i, s in enumerate(scenes):
        if s.speech > 6: warn.append(f"scene {i + 1} is {s.speech:.1f}s of speech; split it")
    words = sum(len(s.words) for s in scenes)
    speech = sum(s.speech for s in scenes)
    wpm = words / (speech / 60) if speech else 0
    info["wpm"] = round(wpm)
    if s.timing_source != "estimated" and not (110 <= wpm <= 215): warn.append(f"speaking rate {wpm:.0f} wpm (comfortable: 120-200)")
    # READABILITY at phone size
    for i, (sc, lay) in enumerate(zip(scenes, renderer.layouts)):
        if lay["size"] < 56: hard.append(f"scene {i + 1} text is only {lay['size']}px; shorten it")
        elif lay["size"] < 68: warn.append(f"scene {i + 1} text is small ({lay['size']}px)")
    # VARIETY / LENGTH
    kinds = {s.kind for s in scenes}
    info["layouts_used"] = sorted(kinds)
    if len(scenes) >= 5 and len(kinds) < 3: warn.append("low layout variety: add a number or a call-to-action scene")
    info["duration_s"] = round(total, 1)
    if total > max_seconds: hard.append(f"reel is {total:.0f}s, over {max_seconds:.0f}s")
    if total < 12: warn.append(f"reel is only {total:.0f}s")
    # TIMING SOURCE
    info["caption_timing"] = scenes[0].timing_source
    if scenes[0].timing_source == "estimated":
        warn.append("captions are timed by estimate, not from the audio (use --tts edge/elevenlabs, or --audio)")
    # CTA
    if len(scenes) > 2 and scenes[-1].kind != "cta": warn.append("no call-to-action scene")
    return {"passed": not hard, "hard_failures": hard, "warnings": warn, "info": info}
