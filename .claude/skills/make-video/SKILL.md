---
name: make-video
description: Make a long-form video (5 minutes to 2 hours: YouTube documentary, explainer, essay, lecture, podcast with visuals) from a request. Researches deeply, plans chapters, writes the script chapter by chapter across sessions, renders with narration, footage, stills, captions and music, and produces a YouTube package (chapters, description with sources, captions file, thumbnail). Use for anything longer than about 3 minutes. For Reels / TikToks / Shorts use make-reel instead.
---

# Make a long-form video

You are the producer, researcher, writer and reviewer. `python run.py long ...` does narration, editing and encoding.
Run commands from the project folder. Use `py run.py` if `python` is not found on Windows. Quote handles in PowerShell.

Long videos cost a lot of your usage allowance and the viewer's patience. Be honest with the user about this
(see "Reality check") before committing to an hour or more.

## 0. Setup
Same as make-reel: `python run.py --setup`, and `PEXELS_API_KEY` in `.env` for stock footage (free key from
https://www.pexels.com/api/). Without it use the user's clips (`--broll-dir`) or accept gradient backgrounds.

## A. Understand and scope
Ask at most 3 questions, only what changes the video:
- **Topic and angle.** What does the viewer learn or feel? What is YOUR take, not just a summary? (See "Originality".)
- **Audience, platform, length.** Default YouTube, landscape 1080p. Suggest a length: explainer 8-15 min, deep dive 20-40 min,
  documentary 45-120 min. Narration is about 150 words per minute (a 30-minute video is about 4,500 words).
- **Voice, tone, any must-include facts, own footage or music.**

## B. Reality check (tell the user in 3-5 lines)
- Writing: a 2-hour video is about 18,000 words, roughly 25,000+ tokens of output plus research. On a $20 plan this
  takes several sessions; the project is saved in files so it resumes. Suggest starting with a 10-minute video or the first chapters.
- Rendering: roughly 0.5x the video length on a fast 8-core machine, longer on a laptop. It is resumable.
- Listening: one synthetic voice for an hour is tiring. The free voices are fine up to about 30 minutes; for longer,
  suggest ElevenLabs (`--tts elevenlabs`, paid by the character; long-form does not support a recorded voiceover yet).
- Monetization: YouTube demonetizes mass-produced, templated or repetitive content. The video needs original
  analysis, a real point of view and varied structure. Stock footage plus synthetic voice over a generic summary may not qualify.
- Accuracy: you can only be as accurate as your sources. Every factual chapter needs sources; the user must review the script.

## C. Research (your web search and fetch tools) - save to `projects/<slug>/research/`
Deeper than a reel: plan roughly 3-6 searches per chapter.
1. Primary and reputable sources (papers, official data, books, major outlets, archives). Note URL, date, the exact fact.
2. What already exists: top videos and articles on this topic; what they cover, what they miss, how long they are, how they
   open and structure it. Find the gap this video fills. Be explicit about what you could not read (many video pages are blocked).
3. Conflicting claims: where sources disagree, say so in the script instead of picking one silently.
4. Never write a number, date, quote or name you did not find in a source. If unsure, leave it out or flag it for the user.

## D. Plan: `projects/<slug>/plan.md` and `plan.json`
- Working title (3 options), the one-sentence promise, the angle, the audience.
- **Chapters:** 5-8 per 20 minutes is a good guide (each 2-6 minutes). For each: title, purpose, key facts with sources,
  the visual idea (what footage, which stills, which fact cards), target words.
- **Retention plan:** a hook in the first 30 seconds that states the promise; a new reveal or question every chapter;
  a pattern interrupt (fact card, still image, change of pace) at least every 2 minutes; an end that pays off the hook.
- **Look, voice, music** as in make-reel (pick by topic; `story` or `explainer` for most long videos; `calm` for essays).
- `plan.json`: `{"target_words_per_chapter": 700}` (used by the progress table).
Show the user the plan and wait for approval before writing. Plan changes are cheap; script rewrites are not.

## E. Write chapter by chapter - `projects/<slug>/chapters/01-name.md`, `02-name.md`, ...
One file per chapter so the work survives across sessions. Write 1-3 chapters per turn, then run
`python run.py long --assemble projects/<slug>` to see the word and minute totals. Keep `projects/<slug>/title.txt`.

Chapter file format:
```
## Chapter title
> broll: harbour at dawn | old wooden ship close up | fishermen pulling nets | foggy coastline
> images: 17th century harbour painting | old nautical map
> source: https://example.org/article | https://example.org/paper
Narration paragraph. Blank line = new paragraph.

> shot: lighthouse beam night
> fact: 1,200 ships a year
Narration paragraph that starts over a specific shot, with a big text card at its start.
```
- `broll`: 3-5 concrete, filmable searches per chapter (2-5 words each). Variety: wide, close-up, people, objects.
  More queries = less repetition. Avoid abstract words. `> shot:` forces a clip for one moment.
- `images`: stills from Wikimedia Commons (CC0 / public domain / CC BY only; credits go in the description). Best for history,
  science, geography, people. Use 2-4 per chapter when the topic suits it.
- `source`: URLs for the chapter's facts (they go in the description). Required for factual chapters.
- `fact`: a short text card (a number, a date, a short phrase) over the start of a paragraph; use about one per 2 minutes.
- Writing rules: write for the ear (contractions, concrete nouns, varied sentence length; mix short punchy lines with longer ones),
  one idea per paragraph (2-5 sentences), no generic filler ("in this chapter", "let's dive in", "without further ado"),
  vary how sentences start, include names, dates and numbers from the research, and make an argument, not a list.
  Open each chapter with a question, a surprising fact or a scene, never with a summary of what is coming.
- Mark claims you are unsure of with `[CHECK]` in your notes (not in the script) and tell the user at the end.

## F. Fact-check pass
Before rendering, reread the assembled `script.md`: list every number, date, name and quote with its source in
`projects/<slug>/factcheck.md`. Remove or fix anything you cannot source. Tell the user the file exists.

## G. Settings: `projects/<slug>/meta.json`
```json
{"title": "Final Title", "look": "story", "music_search": "cinematic", "accent": "orange",
 "description": "2-4 sentence summary for the YouTube description.", "tags": ["a", "b"],
 "thumb_text": "FOUR WORD TITLE", "disclosure": "Narration is AI-generated; footage from Pexels.",
 "broll": ["default fallback query", "another"]}
```
`music_search` may be a list of queries; the engine builds a playlist with crossfades. Missing fields come from the look.

## H. Preview, then render
1. Estimate: `python run.py long projects/<slug>/script.md --meta projects/<slug>/meta.json --plan-only`.
2. Preview the first chapter at low cost: add `--limit-chapters 1 --res 720 --quality fast -o out/<slug>-preview`.
   Read `gates.json`, open a few frames (extract with the bundled ffmpeg), check captions, footage relevance, pacing, the chapter card.
3. Full render **in the background** so it survives long runs:
   `python run.py long projects/<slug>/script.md --meta projects/<slug>/meta.json -o out/<slug> --detach`
   Poll with `python run.py long --status out/<slug>` every few minutes (do not poll more than once a minute).
   If it says STOPPED, run the same command again; finished shots and narration are reused.
   Options: `--res 720 --quality fast` roughly doubles the speed; `--jobs N` parallel renders; `--clips-per-query`.
4. Gates (`!` warnings): fix repeated clips (more `broll` queries), long stretches without a card (`fact` or `images`), templated
   openings, missing sources. Hard failures (`✗`) must be fixed; do not use `--force` unless the user asks.

## I. Review and deliver
Extract frames across the video (chapter starts, a fact card, a still, a mid-chapter caption) and look at them.
Deliver `out/<slug>/`: `video.mp4`, `thumbnail.png`, `description.txt` (chapters, sources, credits), `chapters.txt`, `captions.srt`
(upload as subtitles), `credits.txt`, `gates.json`. Also give 3 title options and a thumbnail text idea. State plainly what you did not
verify (you did not watch the motion or hear the audio; facts are as good as the sources; the user must review the script).
Tell the user to check YouTube's current policies on AI-generated content disclosure and monetization before uploading.

## J. Repurpose into Shorts (optional, high value)
From the finished script pick 3-5 self-contained moments (20-45 s: a surprising fact, a story beat, a myth busted). For each, write a
new short script with a stronger hook (do not just clip the narration) and render it with the make-reel flow
(`python run.py scripts/<name>.txt --meta ... `). Footage already downloaded is cached, so no new downloads for the same queries.
Link them in the long video's description.
