# Topic / script → reel

One command turns a topic or script into a finished reel: voiceover, captions timed to the audio, a lip-synced paper-cut host,
script-matched illustrations, a beat-synced synthesized soundtrack, in any aspect ratio. It also writes `caption.txt`,
`reel.srt`, `poster.png` and review sheets.

## Setup
```
python run.py --setup     # Windows without `python`: py run.py --setup
```
ffmpeg is bundled (`imageio-ffmpeg`). The default voice (Microsoft Edge neural voices) needs internet but **no API key**.

## Use
```
# your own script (blank line = new scene; first = hook, last = call to action)
python run.py examples/en.txt --handle @you

# every aspect ratio from one timeline
python run.py examples/en.txt --formats 9:16,4:5,1:1,16:9

# an LLM writes it (set ANTHROPIC_API_KEY or OPENAI_API_KEY; REEL_LLM_MODEL optional)
python run.py --topic "why cold showers work" --seconds 30 --tone "playful" --mood hype

# no key: you supply the points, it adds a hook formula + CTA
python run.py --topic "cold showers" --points "They spike alertness for 30 minutes;Start with 30 seconds"

# your own recording (Whisper aligns it) and your own face on the host
python run.py script.txt --tts file --audio my_take.m4a --host-photo me.jpg

# other languages
python run.py examples/es.txt --lang es
```
Output goes to `out/` (or the folder of `-o`). With several formats the files are named `reel_9x16.mp4`, `reel_1x1.mp4`, ...
Sample output is in `out/example/`.

## What it does
| Stage | Detail |
|---|---|
| Script | LLM prompt encodes Reels hook rules (hook ≤ 8 words, one idea per scene, one number, CTA that echoes the hook, caption + 3-5 hashtags) and also picks a prop per scene. Long lines are auto-split. |
| Voice | `--tts auto` (default): Edge neural voices (3 tries) → **offline Piper voice** if Edge is down → silent estimate. Every result is cached in `.cache/tts`, so re-renders need no network. Also `elevenlabs`, `openai`, `file` (your recording), `none`. Word timing comes from Edge/ElevenLabs boundaries or local Whisper. |
| Host | A cut-paper presenter that blinks, raises its eyebrows, has a **mouth driven by the voice's loudness**, and gestures on stressed words. `--host-photo me.jpg` puts your face on the body; `--host none` turns it off. |
| Props | 18 drawn illustrations (clock, bulb, phone, drop, heart, star, check, chart, coin, moon, sun, rocket, target, book, fire, camera, lock, mail) chosen from each scene's own words, or by the LLM. No match → no prop; nothing is placed at random. `--no-props` disables. |
| Layouts | hook, card, stat (count-up number), cta (inverted colours + handle pill), chosen automatically |
| Formats | `--formats 9:16,4:5,1:1,16:9`: each ratio has its own layout and safe zones |
| Motion | closed-form springs, accent-wipe transitions, motion blur, word-by-word fill with underline |
| Sound | synthesized music (upbeat, hype, calm, dark; seeded), ducked under the voice, whoosh on cuts, thump on the CTA; cuts on the half-beat grid; -14 LUFS |
| Craft gates | pace (no flat stretch > 1.5 s), hook (≤ 10 words, first word < 0.6 s), text size per format, length, speaking rate, layout variety, caption-timing source |
| Originality gates | cliché openers ("hey guys", "in this video"), hype-word stuffing, near-duplicate scenes, no concrete detail, identical-looking neighbours, and **similarity to your past scripts** (`.reel_history.json`; ≥ 70 % overlap blocks the render; re-rendering the same script file counts as a revision) |
| Extras | `poster.png`, `contact.png` + `phone.png` review sheets, `reel.srt`, `timing.json`, `gates.json` |

Hard gate failures stop the render (`--force` overrides). If Whisper can't be loaded, the run continues with estimated
caption timing and says so. Latin/Cyrillic/Greek/Vietnamese work with the bundled font; for CJK/Arabic/Thai pass `--font`.

## Use it from Claude (desktop app or terminal)
**Claude desktop app (Windows / Mac):** open the app, sign in, click the **Code** tab, choose this folder as the project, and type:
```
/reel why cold showers work, 30 seconds, @yourname, vertical and square
```
**Terminal:** run `claude` inside this folder and type the same line.

Claude writes the script (no API key needed), picks the props, renders a fast draft, looks at the contact sheet, fixes problems,
then renders the final files. The workflow is in `.claude/skills/make-reel/SKILL.md`; house rules in `CLAUDE.md`.
It runs on your computer and needs Python 3.10+ and Git. The first run creates `.venv` and downloads about 135 MB of models.
The claude.ai chat tab cannot run it; use the Code tab. Windows support was added via `run.py` but has not been tested on Windows.

## Limits
- The originality gate is heuristic: it catches generic, repetitive or already-made scripts. It cannot prove a script is novel.
- Props come from a fixed library of 18 drawings and there is one host character; nothing is drawn from scratch per script.
- The Anthropic/OpenAI script step, ElevenLabs and OpenAI TTS follow the providers' documented APIs but were not run (no keys).
  Edge, Piper, Whisper (including recorded-voice alignment), the offline fallback, all four aspect ratios and the gates were run end to end.
- Offline voices sound flatter than Edge or ElevenLabs.
- Rendering is CPU-bound: about 75 s per format for a 14 s reel with motion blur (`--blur 1` is about 3× faster).
- Whisper may place the first word a few tenths of a second off.

See `CLAUDE.md` for house rules and the review loop.
