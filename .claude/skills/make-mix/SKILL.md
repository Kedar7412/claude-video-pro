---
name: make-mix
description: Pick the best video engine for a request (this repo's reel/long pipeline, animate, Remotion or HyperFrames), and switch engines between segments of one video when different parts need different looks. Use for every video request before choosing a pipeline, and whenever one video would be better built from more than one engine.
argument-hint: "[what the video is about]"
---

# Choose the engine, or mix them

You are the director. Four engines are installed; each is best at something. Decide per video, and per segment
when the video changes kind (e.g. a hand-drawn story, then a data chart, then a product screen).

## 1. Intent first
Do phase A-C of `.claude/skills/make-reel/SKILL.md` (intent, research, brief) as usual. The brief now also has an
**Engine plan** row: one engine for the whole video, or a segment list with an engine per segment and why.

## 2. Which engine fits

| Engine | Best for | Avoid for | Skill to follow |
|---|---|---|---|
| **reel** (`python run.py`) | Stock-footage reels with kinetic captions; quick talking-points reels; anything needing Pexels b-roll; long videos (`run.py long`) | Custom illustration, precise UI motion | `make-reel`, `make-video` |
| **animate** | Hand-drawn / illustrated stories and explainers (cut paper, sketchbook, crosshatch, riso, pixel, isometric, math); characters with faces; histories with shape morphs | Real footage, dense data, brand UI | `animate` (`~/.claude/skills/animate`) |
| **Remotion** (`remotion/`) | Data-driven motion graphics: charts, counters, timelines, maps, captions from a transcript, templated series (same layout, new props), app/SaaS UI | Hand-drawn looks | `remotion-best-practices` (router), `remotion-create`, `remotion-render` |
| **HyperFrames** (`hyperframes/`) | Polished HTML/CSS motion design: title cards, kinetic type, launch films, overlays, transitions and ~450 ready blocks (glitch, grain, 3D, charts, map overlays); fast to iterate | Long narrated pieces with heavy per-word timing | `hyperframes` (read first), `hyperframes-registry` |

Tie-breaks: the user named an engine → use it. Footage needed → reel. A face/character carries the story → animate.
Numbers are the story → Remotion. Type and slick transitions are the story → HyperFrames. Unsure → the engine whose
strength is the **hook** scene, since that decides whether people stay.

## 3. When to mix
Mix only when a segment clearly looks better in another engine, not for variety's sake. Good mixes:
- animate story → **Remotion chart** for the one number → animate payoff
- HyperFrames title/hook → **reel** footage body → HyperFrames end card
- reel footage → **HyperFrames** kinetic-type quote overlay scene
Keep the video feeling like one piece: the same accent colour and one font family across engines (pass them as
props / CSS variables), the same aspect ratio, and one narrator.

## 4. Build a mixed video
1. **One voice for the whole video.** Write the full script, then make the narration once (reuse the reel voice:
   `edge-tts --voice <voice> --rate <rate>` from `.venv`, one file per line, or the reel pipeline's own voice) and time
   the lines. Each segment's length = the span of the lines it covers (round to the 0.25 s beat grid).
2. **Render each segment silent at exactly that length** in its own engine (Remotion: `durationInFrames`;
   HyperFrames: the composition duration; animate: `DURATION`; reel: its scenes). Same size and fps everywhere
   (default 1080x1920, 30 fps; mix.py normalises anyway).
3. **Plan** `scripts/<slug>.mix.json`:
```json
{"out": "out/<slug>/mix.mp4", "size": [1080, 1920], "fps": 30,
 "audio": {"voice": "out/<slug>/voice.wav", "music": "path/to/track.mp3", "music_db": -16},
 "segments": [
  {"engine": "hyperframes", "project": "hyperframes", "take": [0, 2.5]},
  {"engine": "animate", "piece": "pieces/<slug>", "transition": {"type": "cut"}},
  {"engine": "remotion", "project": "remotion", "comp": "Stat", "props": {"value": 47}, "transition": {"type": "fade", "d": 0.25}},
  {"engine": "reel", "script": "scripts/<slug>.txt", "meta": "scripts/<slug>.json", "args": ["--style", "cards"]}
 ]}
```
   Without `"audio"`, each segment keeps its own sound (fine when every segment carries its own narration).
4. `python run.py mix scripts/<slug>.mix.json` → `mix.mp4`, `contact.png` (one frame per segment), `mix.json`,
   `segments/`. Re-render one segment with `--only 3`, reuse the rest with `--reuse`.
5. **Review** as CLAUDE.md says: open `contact.png`, check every segment's own review (animate `review.mjs`,
   Remotion/HyperFrames stills, reel `gates.json`), and check the seams: the cut lands on a sentence end, colours and
   type match across engines, no black or frozen frames at a join.

## 5. Report
Say which engine made which segment and why, the review numbers, and what you could not verify (you see stills,
you can't hear the mix). Never claim a segment rendered if it did not.
