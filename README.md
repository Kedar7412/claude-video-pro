# Topic / script → reel

Turns a script into a finished short-form video: full-screen stock footage with a moving camera, bold word-by-word
captions, a natural voiceover, music with cuts on the beat, and a post caption. Built to be driven by Claude Code:
type `/reel <topic>` and Claude writes the script, picks the footage, reviews the frames and renders.

Two looks:
- **footage** (default when footage is available): b-roll from Pexels or your own clips, kinetic captions, title bar, end card.
- **cards** (fallback): animated typographic cards with a paper-cut host and illustrations.

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
**Meta file** (optional JSON): `title`, `broll` (one search query or clip path per scene; `query#2` picks the second result),
`caption`, `hashtags`.

## What it does
| Stage | Detail |
|---|---|
| Footage | Pexels search per scene (cached in `.cache/broll`; no clip used twice), or a local folder matched by file name. Clips are cover-cropped for each aspect ratio and graded. `credits.txt` lists sources. |
| Camera | push-in, pull-out and pans per scene, a punch-in on every cut, a zoom-through into the next cut, a shake on stressed words |
| Captions | 1-3 words at a time in Anton, the spoken word lights up, stressed words get their own big beat, numbers count up, title bar on top, handle pill on the end card. Rows behind the text are darkened so it reads on any footage. |
| Voice | `--tts auto`: Edge neural voice (`en-US-AndrewMultilingualNeural` by default; 8 quick retries) → offline Piper voice → silent. One reel always uses one voice. EQ + compression for presence. Cached in `.cache/tts`. Also `elevenlabs`, `openai`, `file` (your recording). |
| Music | `--music-file`: your track, with tempo and first beat detected so cuts land on its beats (warns if the track has no clear beat). Otherwise a synthesized bed (upbeat, hype, calm, dark) with sidechain pump. Ducked under the voice; whoosh on cuts, riser and hit into the end card; -14 LUFS target. |
| Gates | pace, hook length and timing, caption size per format, length, speaking rate, clip reuse, clichés, hype words, duplicate scenes, similarity to your past scripts (`.reel_history.json`). Hard failures stop the render (`--force` overrides). |
| Extras | `poster.png`, `contact.png` + `phone.png` review sheets, `reel.srt`, `caption.txt`, `timing.json`, `gates.json`, `credits.txt` |

## Limits
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
