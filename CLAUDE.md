# Reel pipeline rules

When asked for a reel/video, follow `.claude/skills/make-reel/SKILL.md` (also available as `/reel <topic>`).

## Code map
`reel.py` (CLI + timing + encode) · `reelkit/script.py` (parse, split, kinds, LLM script) · `voice.py` (TTS + alignment) ·
`music.py` (synth bed, ducking, SFX) · `render.py` (layouts, per-format `Geo`) · `figures.py` (host + props) ·
`checks.py` (craft + originality gates)

## Render contract
- `Renderer.frame(t)` is a pure function of time: no timers, no carried state, no unseeded randomness (music uses a seeded RNG).
- Motion uses `spring()` (closed-form), never linear/ease curves. Tiny overshoot on UI, none on large type.
- Scene lengths are padded to half-beats so every cut lands on the music grid. Sound hits go on cuts.
- Output 1080x1920, 30 fps, H.264 yuv420p, loudness -14 LUFS. Keep text inside the safe zones.

## Look
- Props are chosen from the scene's own words; never add a decorative prop the script doesn't justify.
- Every aspect ratio has its own `Geo`; check each format's `contact_<fmt>.png` after layout changes.
- Banned: centered title on a plain gradient with everything fading in, corner labels, frame borders, glows, particle bursts.
- One font family, one accent colour per scene. Something new on screen at least every 1.5 s (gate enforces it).

## Script rules (also in the LLM prompt)
- Hook ≤ 8 words, lands in the first 2 s. One idea and ≤ 12 words per scene. One concrete number. Last scene = CTA echoing the hook.
- Never invent statistics or testimonials.

## Review loop (before showing the user)
1. Run `python reel.py ...` and read `gates.json`.
2. Open `contact.png` (one frame per scene) and `phone.png` (360px-wide strip) and LOOK at them. Re-open under a new filename if the viewer shows a cached image.
3. Score 1-10: hook in first 2 s, readability at phone size, motion, variety, sync. Fix the 3 worst problems; repeat until all are 8+.
