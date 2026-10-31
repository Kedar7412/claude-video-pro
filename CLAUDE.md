# Reel pipeline rules

When asked for a reel/video, follow `.claude/skills/make-reel/SKILL.md` (also available as `/reel <topic>`).

## Code map
`reel.py` (CLI, timing, encode) · `run.py` (venv launcher) · `reelkit/script.py` (parse, *emphasis*, kinds, LLM script) ·
`voice.py` (TTS, alignment) · `music.py` (synth, track loading, beat detection, voice polish, mix) ·
`footage.py` (Pexels/local clips, frame streaming, camera) · `kinetic.py` (footage style renderer) ·
`render.py` + `figures.py` (cards style, host, props) · `checks.py` (gates)

## Render contract
- `frame(t)` is a function of time; footage is streamed sequentially and re-opened with a seek for random access.
- Motion uses `spring()` / smoothstep, never linear moves.
- Scene lengths are padded to half-beats so every cut lands on the music grid. Sound hits go on cuts.
- Output H.264 yuv420p, 30 fps, -14 LUFS target. Keep text inside each format's safe zone.

## Look
- Footage must show what the line is about. Swap the query rather than keep an unrelated clip.
- Captions: at most 3 words on screen, one highlighted word, at most one or two stressed words per scene.
- Banned: centered title on a plain gradient, everything fading in, corner labels, frame borders, glows, particle bursts.

## Script rules
- Hook ≤ 8 words, said in under 2 s. One idea and ≤ 12 words per scene. One concrete number. Last scene = CTA.
- Never invent statistics, studies, quotes or testimonials.

## Never commit
`.env` (API keys), `.cache/`, `models/`, `out/`.
