# Reel pipeline rules

Reels / TikToks / Shorts (under ~90 s): follow `.claude/skills/make-reel/SKILL.md` (`/reel <topic>`).
Long videos (5 min to 2 hours): follow `.claude/skills/make-video/SKILL.md` (`/video <topic>`).
Always go through intent → research → brief before writing a script; the brief is what makes each reel fit its topic.

## Code map
`reel.py` (CLI, timing, encode) · `run.py` (venv launcher) · `reelkit/script.py` (parse, *emphasis*, kinds, LLM script) ·
`voice.py` (TTS, alignment) · `music.py` (synth, track loading, beat detection, voice polish, mix) ·
`footage.py` (Pexels/local clips, frame streaming, camera) · `kinetic.py` (footage style renderer) ·
`looks.py` (look presets) · `longform.py` / `longscript.py` / `images.py` (long videos: ffmpeg-composed shots, ASS captions, YouTube package) · `musicsearch.py` (CC0/CC BY music from Wikimedia Commons) ·
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
- Never invent statistics, studies, quotes or testimonials. Numbers must come from the research notes (with a source) or the user.

## Never commit
`.env` (API keys), `.cache/`, `models/`, `out/`.

## Long-form rules
- Keep grades to `eq` and `lutyuv`; `colorbalance` and `curves` cost 5-10x the render time.
- Each shot is one ffmpeg call; caption lines never straddle a cut; shot lengths are frame-snapped so audio and video stay in sync.
- Never claim a long render was run if it was not; report what was tested.
