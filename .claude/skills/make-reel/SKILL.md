---
name: make-reel
description: Make a finished short-form video (Reel / TikTok / Short) from a topic or script, with stock footage, kinetic captions, voiceover, music and a post caption. Use when the user asks for a reel, TikTok, short, promo clip or explainer video.
---

# Make a reel

You (Claude) are the scriptwriter, footage picker and reviewer. `reel.py` does the voice, editing and encoding.
No LLM API key is needed: you write the script yourself. Run commands from the project folder.

Commands below use `python run.py`. If `python` is not found on Windows, use `py run.py`. In PowerShell, always quote
handles: `--handle '@name'` (an unquoted @ is PowerShell syntax and the handle disappears).

## 0. One-time setup
- If `.venv` is missing: `python run.py --setup`.
- Footage needs a free Pexels key. Check `.env` for `PEXELS_API_KEY=`. If it is missing, tell the user:
  "Make a free account at https://www.pexels.com/api/, copy your API key, and paste it here." Then write the line
  `PEXELS_API_KEY=<key>` to `.env` (never print the key back, never commit `.env`).
  Without a key, either use the user's own clips (`--broll-dir folder`) or fall back to `--style cards`, and say so.

## 1. Collect inputs (ask only for what is missing; offer defaults)
Topic or finished script · handle · language (default English) · length (default 25-35 s) · formats (default 9:16;
also 4:5, 1:1, 16:9) · music: their own royalty-free track (best) or the built-in synth · facts or numbers they want used.

Never invent statistics, studies, quotes or testimonials. If the user gave no facts, write advice or opinion
("Start with 30 seconds"), not data ("Studies show 47%..."). If a claim needs a source, ask for it.

## 2. Write the script: `scripts/<slug>.txt`
One scene per paragraph (blank line between). 6-8 scenes, 55-90 words total.

**Structure**
1. **Hook (scene 1), at most 8 words.** It must make a scroller stop. Pick one pattern:
   - Call out a mistake: "You're ending your shower wrong."
   - Contrarian claim: "Cold showers don't burn fat."
   - Specific result: "I took cold showers for 30 days."
   - Curiosity gap: "Nobody tells you the last 30 seconds matter."
   Never open with a greeting, "In this video", "Today we", "Did you know", or context-setting.
2. **Stakes or open loop (scene 2):** why it matters, or a promise that keeps them watching ("The third one is the one people skip.").
3. **Body (3-4 scenes):** one idea each, each with a concrete detail (a number, an object, a time, a sensation).
   Put the strongest or most surprising point last.
4. **Payoff + call to action (last scene):** one action and one reason ("Follow for the next habit that actually sticks.").
   Echo the hook if you can, so the loop back to the start feels deliberate.

**Line rules**
- At most 12 words per scene, one sentence. Write for the ear: contractions, short words, "you".
- No filler ("basically", "actually" unless it carries meaning), no hype words (insane, game-changer, secret, unlock).
- Mark the ONE word you would stress out loud in each scene with asterisks: `It takes *30* days.`
  Stressed words get their own big caption beat, the accent colour and a camera shake. One per scene, never more than two.
- Put exactly one concrete number in digits somewhere (it gets a count-up animation).

**Self-check before rendering (rewrite once if any answer is no)**
- Would the hook alone stop you scrolling? Is it under 2 seconds to say?
- Does every scene add something new? Could you delete one without losing anything? (Then delete it.)
- Is there a specific detail a generic AI script would not have?

## 3. Write `scripts/<slug>.json`
```json
{"title": "COLD SHOWER RULE",
 "broll": ["cold shower water close up", "wall clock ticking close up", "heart rate monitor", "man waking up morning bed",
           "hand turning shower tap", "sunrise over city"],
 "caption": "You're ending your shower wrong.\n\nThe last 30 seconds do the work.\n\nSave this for tomorrow morning.",
 "hashtags": ["coldshower", "morningroutine", "habits"]}
```
- `title`: 2-4 words in capitals, shown at the top the whole time. Use "" for none.
- `broll`: one stock-footage search per scene, in order. 2-5 concrete, filmable words: objects, actions, places
  ("hand turning shower tap", "runner tying shoes"). Never abstract ideas ("motivation", "productivity").
  Vary the shots (close-up, wide, people, objects). Avoid queries likely to return text-heavy screens or logos.
  To get a different result for the same query, add `#2`, `#3`: `"sunrise over city#2"`.
  A scene can also use a local file path instead of a query.
- `caption`: line 1 repeats the hook (the only line visible before "more"), 1-2 lines of extra value, then the CTA.
- `hashtags`: 3-5 specific tags, not generic ones like fyp.

## 4. Draft and review (fast)
```
python run.py scripts/<slug>.txt --meta scripts/<slug>.json --handle '@name' --blur 1 -o out/<slug>/draft.mp4
```
Add `--music-file path` if the user has a track. Add `--style cards` only if there is no footage source.
- If the gates print `✗`, fix the script and re-run. Do not use `--force` unless the user asks.
- Read the `!` warnings. Fix "reuse a clip" by giving those scenes different queries.
- Open `out/<slug>/contact.png` and `phone.png` and LOOK at them. Check each frame:
  - Does the footage show what the line is about? If not, change that scene's query (or add `#2`).
  - Watermarks, burned-in text, logos, or a face cut in half by the caption? Change the query.
  - Are the captions readable at phone size? Is the hook's first frame strong?
- Score 1-10: hook, footage relevance, readability, pacing, variety. Fix the 3 worst problems and re-run.
  At most 3 rounds unless the user wants more. Re-open an image under a new filename if the viewer shows a stale one.

## 5. Final render
Same command without `--blur 1`, `-o out/<slug>/reel.mp4`, plus `--formats 9:16,1:1,16:9` if requested.
Expect about 1-2 minutes per format for a 30-second reel.

## 6. Deliver
Report the files (`reel*.mp4`, `poster*.png`, `caption.txt`, `reel.srt`, `credits.txt`), the duration, any remaining
gate warnings, and what you would improve next. Say plainly that you reviewed still frames and the gate report;
you cannot watch the motion or hear the audio, so the user should watch it once before posting.

## Useful flags
`--accent yellow|green|orange|pink|cyan` · `--title "..."` · `--music-file track.mp3 --music-start 12` ·
`--voice en-US-AvaMultilingualNeural` (female) · `--tts elevenlabs --voice <id>` (needs `ELEVENLABS_API_KEY` in `.env`) ·
`--tts file --audio take.m4a` (the user's own recording) · `--lang es` · `--broll-dir folder` · `--style cards`.
