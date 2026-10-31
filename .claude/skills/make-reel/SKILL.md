---
name: make-reel
description: Make a finished vertical (or square / landscape) short-form video from a topic or script, with voiceover, timed captions, a paper-cut host, illustrations, music and a post caption. Use when the user asks for a reel, TikTok, short, promo clip or explainer video.
---

# Make a reel

You (Claude) are the scriptwriter and reviewer; `reel.py` does the voice, animation and encoding. No LLM API key is needed
because you write the script yourself.

## 0. One-time setup (skip if `.venv` exists)
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python reel.py --setup
```

## 1. Collect inputs (ask only for what is missing; offer defaults)
Topic or finished script · handle (e.g. @name) · language · length (default 30 s) · mood (upbeat/hype/calm/dark) ·
formats (default 9:16; also 4:5, 1:1, 16:9) · host photo (optional) · call to action.
Never invent statistics, testimonials or claims about a product. If the user gives facts, use only those.

## 2. Write the script to `scripts/<slug>.txt`
One scene per paragraph (blank line between). Rules:
- Scene 1 is the hook: at most 8 words, payoff first, a specific claim or number. Never "Hey guys", "In this video", "Today we".
- One idea per scene, at most 12 words, written for the ear.
- Exactly one scene containing a concrete number (digits).
- Last scene is the call to action, giving one reason to act and echoing the hook if possible.
- About 5-8 scenes, roughly 2.7 words per second of target length.

Also write `scripts/<slug>.json`:
```json
{"caption": "hook line\n\n1-2 lines of value\n\nCTA line", "hashtags": ["specific", "tags", "3to5"],
 "props": ["clock", "", "chart", ""]}
```
`props` has one entry per scene, from: clock bulb phone drop heart star check chart coin moon sun rocket target book fire camera lock mail,
or "" when none fits (the last scene never shows one). Choose only props that the scene's words justify.

## 3. Draft render and review (fast)
```
.venv/bin/python reel.py scripts/<slug>.txt --meta scripts/<slug>.json --handle @name --mood upbeat --blur 1 -o out/<slug>/draft.mp4
```
- If the gates print `✗` failures, fix the script (they say what) and re-run. Do not use `--force` unless the user asks.
- Open `out/<slug>/contact.png` and `phone.png` and LOOK at them. Score 1-10: hook in the first 2 s, readability at phone size,
  variety, prop relevance, sync. Fix the 3 worst problems (usually: shorten a line, change a prop, change a scene's wording) and repeat
  until everything is 8 or higher. Maximum 3 rounds unless the user wants more.
- Re-open an image under a new filename if the viewer shows a stale one.

## 4. Final render
Same command without `--blur 1` (motion blur on), plus `--formats 9:16,1:1,16:9` if requested, `-o out/<slug>/reel.mp4`.
Rendering takes about 75 s per format per 14 s of video; tell the user to expect it.

## 5. Deliver
Report: the file paths (`reel_*.mp4`, `poster.png`, `caption.txt`, `reel.srt`), the duration, the gate warnings that remain, and
what you would improve next. State plainly what you did not verify (you cannot watch motion or hear audio; you reviewed stills
and the gate report).

## Useful flags
`--host none` · `--host-photo me.jpg` · `--no-props` · `--palette studio|ink|ochre` · `--voice en-US-AriaNeural` ·
`--tts file --audio take.m4a` (use the user's own recording) · `--lang es` · `--font path.ttf` for CJK/Arabic/Thai.
