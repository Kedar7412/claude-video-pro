# Topic / script → reel

Turns a request into a finished short-form video. Driven by Claude Code: type `/reel <what you want>` and Claude
1. works out the intent (tips, story, promo, mystery, mood, humour...), audience and desired action,
2. researches the topic (facts with sources) and similar successful short videos (hooks, length, pacing, shot types, music vibe),
3. writes a creative brief (duration, hook, structure, look, voice, music, footage types) and checks it with you,
4. scripts, renders a draft, reviews the frames against the brief, fixes problems and renders the final.

Research notes go to `scripts/<slug>.research.md` and the brief to `scripts/<slug>.brief.md`.

**Looks** (`--look` or `"look"` in the brief) set captions, camera, cuts, colour grade, music mood and voice together:

| Look | Captions | Camera / cuts | Grade | Voice (default) | Music mood |
|---|---|---|---|---|---|
| hype | Anton caps, outlined, colour highlight | strong moves, punches, shakes, flash cuts | punchy | Guy (passion), +12% | hype |
| explainer | Montserrat, accent box behind the spoken word | gentle, zoom cuts | clean | Andrew (warm, confident) | upbeat |
| calm | Playfair serif, words fade in | slow drift, crossfades | warm | Ava (caring), -4% | calm |
| story | Montserrat sentence case | measured, crossfades | film | Christopher (authority) | cinematic |
| dark | Anton caps, red | slow, dips to black | cold, desaturated | Christopher, lower pitch | dark |
| luxury | Playfair caps, small, fade in | slow, crossfades | gold | Aria (positive, confident), -6% | lofi |
| funny | Anton caps, 2 words at a time | snappy, flash cuts | bright | Brian (casual), +10% | upbeat |

Any part can be overridden per reel (`look_overrides` in the JSON). Without footage the older **cards** style is used.

## Setup
```
python run.py --setup          # Windows without `python`: py run.py --setup
```
Then add a free Pexels API key for footage (https://www.pexels.com/api/) to a file named `.env` in this folder:
```
PEXELS_API_KEY=your_key_here
```
ffmpeg and the fonts (Anton, Montserrat; SIL Open Font License, in `assets/fonts`) are bundled. The default voice
(Microsoft Edge neural voices) needs internet but no key.

## Use it from Claude (desktop app or terminal)
**Claude desktop app:** sign in, click the **Code** tab, choose this folder, and type:
```
/reel why cold showers work, 30 seconds, @yourname
```
**Terminal:** run `claude` in this folder and type the same line.

The workflow Claude follows is in `.claude/skills/make-reel/SKILL.md` (script structure, footage queries, review loop).
It runs on your computer and needs Python 3.10+. The claude.ai chat tab cannot run it; use the Code tab.

## Use it directly
```
python run.py examples/en.txt --meta examples/en.json --handle '@you'          # footage (needs key or --broll-dir)
python run.py examples/en.txt --broll-dir my_clips --music-file track.mp3      # your own clips and music
python run.py examples/en.txt --formats 9:16,1:1,16:9                          # several aspect ratios
python run.py examples/en.txt --style cards                                    # the card look, no footage
```
In PowerShell, put handles in quotes: `--handle '@you'`. Output goes to `out/` (or the folder of `-o`).

**Script format:** one scene per paragraph. Mark the stressed word with asterisks: `It takes *30* days.`
**Settings file** (optional JSON, written by Claude from the brief): `look`, `look_overrides`, `duration`, `voice`, `rate`,
`pitch`, `music_search`, `music_file`, `accent`, `title`, `broll` (one query or clip path per scene; `query#2` = second result),
`caption`, `hashtags`. See `.claude/skills/make-reel/SKILL.md` for the full list.

`python run.py --list-voices en-US` lists voices with Microsoft's personality tags.
`--music-search "calm piano"` fetches a CC0 / CC BY track from Wikimedia Commons and adds the required credit to the caption.

## What it does
| Stage | Detail |
|---|---|
| Footage | Pexels search per scene (cached in `.cache/broll`; no clip used twice), or a local folder matched by file name. Clips are cover-cropped for each aspect ratio and graded. `credits.txt` lists sources. |
| Camera | push-in, pull-out and pans per scene, a punch-in on every cut, a zoom-through into the next cut, a shake on stressed words |
| Captions | 1-3 words at a time in Anton, the spoken word lights up, stressed words get their own big beat, numbers count up, title bar on top, handle pill on the end card. Rows behind the text are darkened so it reads on any footage. |
| Voice | `--tts auto`: Edge neural voice (`en-US-AndrewMultilingualNeural` by default; 8 quick retries) → offline Piper voice → silent. One reel always uses one voice. EQ + compression for presence. Cached in `.cache/tts`. Also `elevenlabs`, `openai`, `file` (your recording). |
| Music | `--music-search`: a CC0 / CC BY track from Wikimedia Commons (BY-SA and NC are skipped), credited in `caption.txt` and `credits.txt`. `--music-file`: your track, with tempo and first beat detected so cuts land on its beats (warns if the track has no clear beat). Otherwise a synthesized bed (upbeat, hype, calm, dark) with sidechain pump. Ducked under the voice; whoosh on cuts, riser and hit into the end card; -14 LUFS target. |
| Gates | pace, hook length and timing, caption size per format, length, speaking rate, clip reuse, clichés, hype words, duplicate scenes, similarity to your past scripts (`.reel_history.json`). Hard failures stop the render (`--force` overrides). |
| Extras | `poster.png`, `contact.png` + `phone.png` review sheets, `reel.srt`, `caption.txt`, `timing.json`, `gates.json`, `credits.txt` |

## Limits
- Research uses whatever Claude's web tools can read. Instagram and TikTok often block logged-out pages, and Claude cannot
  watch videos or hear audio, so "what works" comes from titles, descriptions, transcripts and articles, not from viewing.
  View counts are only reported when a page shows them.
- Music search covers Wikimedia Commons only; its library is smaller than paid stock sites. Trending sounds can't be used
  directly; render with `--music none` and add the sound inside Instagram.
- Footage quality depends on what Pexels has for each query. Claude reviews the contact sheet and swaps bad clips, but only
  from still frames.
- The live Pexels API was not called during development (no key); the code was tested against stubbed responses and with local clips.
  ElevenLabs, OpenAI TTS and the LLM `--topic` mode were also written to documented APIs without a live test.
- Beat detection was checked on synthesized tracks (within 10 ms) and two real tracks; unusual music may confuse it.
- Edge voices are an unofficial use of a free Microsoft service with no guarantee; check its terms before commercial use.
  The offline fallback voice sounds flatter.
- Footage reels are rendered at about 4-8 frames per second of CPU time per format; a 30 s reel takes 1-3 minutes.
- Audio is mono.

See `CLAUDE.md` for house rules.
