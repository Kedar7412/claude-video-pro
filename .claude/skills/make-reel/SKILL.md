---
name: make-reel
description: Make a finished short-form video (Reel / TikTok / Short) from a request. First works out the intent, researches the topic and similar successful short videos, and writes a creative brief (duration, hook, tone, voice, music, look, footage types); then scripts, renders and reviews it. Use when the user asks for a reel, TikTok, short, promo clip or explainer video.
---

# Make a reel

You (Claude) are the producer: researcher, scriptwriter, footage picker and reviewer. `reel.py` does the voice,
editing and encoding. No LLM API key is needed. Run commands from the project folder.

Commands use `python run.py`. If `python` is not found on Windows, use `py run.py`. In PowerShell, always quote handles:
`--handle '@name'`.

## 0. One-time setup
- If `.venv` is missing: `python run.py --setup`.
- Footage needs a free Pexels key in `.env` (`PEXELS_API_KEY=...`). If missing, ask the user to create one at
  https://www.pexels.com/api/ and paste it; write it to `.env` yourself (never echo it, never commit `.env`).
  Without a key, use the user's clips (`--broll-dir`) or `--style cards`, and say so.

Every reel goes through phases A to G. Do not skip A-C: they are what make each reel fit its topic.

## A. Understand the request
Work out, from the user's words (ask at most 2 questions, only if the answer changes the video):
- **Intent:** educate / tips · story / case study · motivate · mystery / warning · promote / sell · aesthetic / mood · humour.
- **Audience** and **platform** (default Instagram Reels), **desired action** (follow, save, comment, buy, visit).
- **Constraints:** handle, language, must-say facts, brand colours, the user's own clips or music.

## B. Research (use your web search and web fetch tools)
Spend about 5-10 searches. Save notes with source URLs to `scripts/<slug>.research.md`.
1. **Facts.** Find 3-6 accurate, specific facts about the topic from reputable sources (official bodies, studies,
   major publications). Only facts you found with a source may appear as numbers or claims in the script.
2. **What works in this niche.** Search for successful short videos close to the request, for example
   `"<topic>" reel`, `"<topic>" tiktok`, `"<topic>" shorts`, `best <niche> reels hooks`, `<niche> viral short video format`.
   Read what is reachable: video titles and descriptions, YouTube Shorts pages, transcripts, creator or marketing
   articles that analyse top posts. Note for the closest examples:
   - the hook line or pattern, length, pacing (how often the shot changes), who or what is on screen
     (b-roll, talking head, screen recording, text-only), caption style, music vibe, the call to action.
   - view or like counts **only if the page shows them**. Never guess popularity.
3. **Be honest about limits.** Instagram and TikTok often block logged-out pages, and you cannot watch videos or hear
   audio. Base conclusions on what you could read, and say in the brief what you could not check.
4. Take **patterns**, never someone else's script, footage or audio.

## C. Creative brief: `scripts/<slug>.brief.md`
Decide each item below and give a one-line reason that points to the research. Then show the user a short summary
(5-8 lines) and ask "Go ahead?" once. Skip the question if they said to just make it.

| Decision | How to choose |
|---|---|
| Duration | Starting points (adjust to what the research showed): humour 7-20 s · aesthetic 10-20 s · motivate 15-30 s · promote 15-30 s · tips 25-40 s · mystery 30-50 s · story 45-75 s |
| Hook | Write 3 candidate hooks using patterns seen in the research (mistake call-out, contrarian claim, specific result, curiosity gap, "POV:"), pick the strongest, and say why |
| Structure | tips: hook → stakes → 3 points → payoff → CTA · story: hook → setup → turn → reveal → CTA · promote: problem → product → proof → offer → CTA · mystery: hook → detail → twist → open loop ("part 2") |
| Look | `hype` (fast, loud) · `explainer` (clear, boxed highlight) · `calm` (soft serif, slow fades, warm) · `story` (cinematic, film grade) · `dark` (cold, red, dips to black) · `luxury` (elegant serif, gold) · `funny` (snappy, bright) |
| Voice | Run `python run.py --list-voices en-US` (or the user's language) and pick by Microsoft's personality tags. Rough guide: hype → Guy (Passion) or Roger (Lively) · tips → Andrew (Warm, Confident) or Emma (Cheerful, Clear) · calm → Ava (Caring) or Jenny (Comfort) · story / dark → Christopher (Reliable, Authority) or Eric (Rational) · luxury → Aria (Positive, Confident) · humour → Brian (Casual). Rate -10% to +15%, pitch -6Hz to +4Hz. |
| Music | A royalty-free search that fits the look: hype "energetic electronic", explainer "upbeat corporate", calm "calm piano", story "cinematic", dark "suspense", luxury "lounge jazz", funny "quirky". Or the user's own track. If the user wants a trending sound, render with `--music none` and tell them to add it inside Instagram, where the licensing is handled. |
| Footage types | The kind of shots the niche uses: macro close-ups, hands doing the action, POV, people reacting, landscapes, timelapse, city, product. Write them into the b-roll queries. |
| Accent / title | Accent colour from the look or the brand. A 2-4 word title only if the research shows series-style titles help in this niche. |

## D. Script: `scripts/<slug>.txt`
One scene per paragraph; aim for the brief's duration at about 2.6 spoken words per second.
- Scene 1 is the chosen hook: at most 8 words. Never open with a greeting, "In this video", "Today we" or context.
- One idea per scene, at most 12 words, written for the ear (contractions, short words, "you").
- Mark the ONE stressed word per scene with asterisks: `It takes *30* days.` (big caption beat, accent colour).
- Put numbers in digits; use only numbers from your research notes or from the user.
- No hype filler (insane, game-changer, secret, unlock). The last scene is the call to action from the brief.
- Self-check, and rewrite once if any answer is no: would the hook stop you scrolling? Does every scene add something?
  Is there a specific detail a generic script would not have?

## E. Settings: `scripts/<slug>.json`
```json
{"look": "story", "duration": 50,
 "voice": "en-US-ChristopherNeural", "rate": "+2%", "pitch": "-2Hz",
 "music_search": "cinematic", "accent": "orange", "title": "",
 "look_overrides": {"camera": {"amount": 0.5}, "caption": {"size": 0.9}},
 "broll": ["old pocket watch macro close up", "foggy london street night", "hands opening old letter", "..."],
 "caption": "hook line\n\n1-2 lines of value\n\nCTA line", "hashtags": ["specific", "tags"]}
```
- Every field except `broll` is optional; missing ones come from the look.
- `look_overrides` can change: `caption` (`font` anton/montserrat/playfair, `weight`, `case` upper/sentence, `size`, `words`,
  `chars`, `highlight` color/box/reveal, `stroke`, `pos`), `camera` (`amount`, `punch`, `shake`, `exit_zoom`),
  `cut` (flash/zoom/fade/dip/hard), `grade` (punchy/clean/warm/film/cold/gold/bright/none).
- `broll`: one query per scene, in order, 2-5 concrete filmable words, matching the brief's footage types.
  Never abstract ideas. `query#2` picks the second result. A local clip path also works.
- `caption`: line 1 repeats the hook. `hashtags`: 3-5 specific tags. Music credits are added automatically.

## F. Draft, review, fix
```
python run.py scripts/<slug>.txt --meta scripts/<slug>.json --handle '@name' --blur 1 -o out/<slug>/draft.mp4
```
- `✗` = gate failure: fix the script and re-run (no `--force` unless asked). Read every `!` warning, especially
  duration vs the brief, clip reuse, and "no clear beat" (fine for calm or story music).
- Open `out/<slug>/contact.png` and `phone.png` and look at every frame against the brief:
  footage matches the line and the planned shot type? No watermarks, logos, burned-in text, faces cut by captions?
  Captions readable at phone size? Does the first frame carry the hook? Does it feel like the chosen look?
- Score 1-10 on hook, fit to the brief, footage relevance, readability, pacing. Fix the 3 worst issues
  (query, `#2`, a line, a look override) and re-run. At most 3 rounds unless the user wants more.
  Re-open an image under a new filename if the viewer shows a stale one.

## G. Final render and delivery
Run the same command without `--blur 1`, with `-o out/<slug>/reel.mp4` and `--formats ...` if requested.
Report: the brief in 4-6 lines (intent, duration, hook, look, voice, music, footage types, and the research behind them),
the files (`reel*.mp4`, `poster*.png`, `caption.txt`, `credits.txt`, `reel.srt`), remaining warnings, and what you
could not verify (you reviewed still frames and read sources; you did not watch the motion, hear the audio, or see
the reference videos themselves). Suggest the user watch it once before posting.
