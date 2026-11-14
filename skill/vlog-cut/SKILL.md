---
name: vlog-cut
description: >-
  Turn a folder of raw vlog/travel footage (SHOTS), photos (PICS) and a song into a story-driven, beat-synced
  Final Cut Pro edit (FCPXML), then layer sound design, handwritten stamps and a photo recap on top of the
  user's own hand edit. Use this whenever the user wants to edit a new movie/vlog/video from their footage,
  make a cut for Final Cut Pro, mentions SHOTS/PICS folders, a song for a video, FCPXML, a recap card, stamps,
  or brings back a .fcpxmld export to finish, even if they don't say "vlog-cut". Also use it to iterate on an
  existing cut from that workflow.
---

# vlog-cut

The user shoots short personal films (drives, trips, nights out, birthdays), typically on a Sony camera, and
finishes them in Final Cut Pro. This skill reproduces a workflow built on a first film (a drive through Paris):
local AI analysis -> story agreed with him -> beat-synced FCPXML -> he edits + grades in Final Cut ->
you layer sound, stamps and recap on his export -> learn from his final edit.

Everything lives in `~/Dev/movie-making` (scripts, editor, models). Read `~/Dev/movie-making/STYLE.md`
before planning any cut: it is the user's taste, learned the hard way, and it grows after every movie.
Commands and file formats: `references/commands.md`.

## His defaults (change per movie only if he asks)

- **~1 minute**, story first, one shot per story beat, no near-duplicate shots, hard cuts only.
- **Pacing follows the song**: slow in quiet parts, fast in loud/instrumental parts. Verses: one shot per
  sung line (~4 beats). Drops: 2-beat cuts. Cut 1 frame before the beat, on movement.
- **Never cut lyrics mid-line**; music edits splice on bar lines, same phrase position, in vocal gaps,
  hidden under a picture cut, and should sound seamless.
- **Never cut people mid-sentence** (speech in clips): keep camera sound up on those shots.
- **Recap after the intro**: polaroid prints landing on textured black (2-3 frames each, card slaps),
  then a torn lined notebook card with his story, held just long enough to read.
- **Handwritten stamps** (`HHhMM · lieu`, font penoftruth, accents auto-stripped) at each chapter / place,
  lasting the whole shot they label. Text in **French** unless he says otherwise.
- **Subtle sound design** from Final Cut's own library, smooth volume ramps everywhere, mix to
  −14 LUFS / true peak ≤ −1 dBTP, camera sound muted where it adds nothing.
- He **grades himself** (Custom LUT + Color Adjustments on adjustment clips). Never auto-grade over it.
- Outputs go to `<movie folder>/AI/` sorted by kind (`fcpxml/ stills/ thumbnails/ previews/ audio/`),
  never inside the tool folder. Analysis cache stays in `~/Dev/movie-making/work/<movie>/`.

## The workflow

### 1. Set up the movie

The movie folder looks like `.../MOVIES/<name>/{SHOTS, PICS, <song file>}`. Create
`~/Dev/movie-making/projects/<slug>.json` (copy `projects/example.json`; set `context`, `name`, `shots_dir`,
`pics_dir`, `music`, `work_dir`, `fcp_event`) and run every script with `VLOG_PROJECT=projects/<slug>.json`.
If there's no song, ask whether it's an original-sound edit before going on.

### 2. Analyse (local, nothing leaves the Mac)

Run in parallel where possible (clips + music + speech are independent; the vision pass needs the clip pass):
`analyze_clips.py` → `describe_clips.py` (Qwen3-VL, ~2.5 s/frame, run in background) → `shotlog.py`;
`analyze_music.py`; `transcribe_music.py` (vocal line timings); `transcribe_clips.py` (speech in clips);
`overview.py`. Then look at `overview.jpg` and the contact sheets yourself: the vision model's landmark
names are unreliable (it called the Orsay clock "Gare du Nord"); trust your own eyes for places.

### 3. Interview him, then agree the story (the one checkpoint)

The first card written from footage alone was rejected as "cringy AI". So before drafting, ask 3-4 short
questions (AskUserQuestion, 3 options + free text, recommended first): who was there, why they went out,
what the moment felt like, any line he already has in mind. Draft the card **from his words**, plain and
first person: a moment, not a list of places.

Then present, in one message: the story in a few lines, the music edit (which song sections, where it's
spliced, proof no sung line is cut), and the shot list as a table (chapter · shot · beats · why). Wait for
his OK before building. This replaces most of the 22 versions the first film needed.

### 4. Build the first cut

Write `edit/<slug>-v1.json` (plan format in references) and run `build_fcpxml.py`. It validates against Final
Cut's own DTD and refuses music edits that cut vocals. Before handing over, check: every cut on the beat
grid (−1 frame), every edit inside its media, no shot starting on dark/dull frames (check brightness
*and* skip lead-ins: he trimmed one shot by a full second past the black), chapter starts on their
musical sections, length near target. Import path for him: File > Import > XML.

### 5. Iterate

Small, quick versions. When he asks for visual fine-tuning (sizes, spacing, wording, stamp timing), point
him to the editor rather than going back and forth: he asked for this explicitly:
`uv run scripts/editor.py` → http://localhost:8765 (run it in a terminal tab so it stays up).

### 6. After he edits in Final Cut (the layering loop)

He exports a `.fcpxmld` into `AI/fcpxml/`. Then:
1. `diff_fcpxml.py <your last build> <his export>`: report what he changed (ignore lane renumbering and
   "1.0dB"→"1dB" noise) and add real lessons to STYLE.md.
2. Layer on top of **his** export with `augment_fcpxml.py` / the editor's Build: audio gains, mutes,
   volume ramps (`volume_keys`, `fades`), sound effects, stamps, recap stills. His cut and grade must stay
   byte-identical: verify that every time.
3. `mixdown.py` → confirm ≈ −14 LUFS and true peak ≤ −1 dBTP; find and fix peaks (card slaps overlap).

### 7. Deliverables

**Title and description** in `AI/desc/` (`title.txt`, `description.txt`), from his **final** export:
- Timestamps in YouTube format, one per line, **`mm:ss text`**: `00:07 17h42 on part en ville` (no `·` or other separators).
  `video_chapters.py "<final>.fcpxmld"` prints exactly that, with the stamps' real positions from his edit and
  their text from the editor state. Never take times from your own last build; he nudges things by frames.
- **Never use em dashes or en dashes (U+2014, U+2013)** anywhere in titles, descriptions or any text written for him.
  Use a comma, a colon or a new line instead.
- Title: his card title, as he wrote it (lowercase style, accents kept: YouTube has no font problem).
- Description: open with **his card text verbatim**, then the timestamps, then place + date and the music
  credit (`musique : Artist, Song`). No hashtags, no marketing tone, no AI-sounding summary; if something
  more is needed, ask him rather than invent it.
- If stamps are < 10 s apart, tell him YouTube will show them as clickable timestamps, not chapters.

Thumbnail in the recap style (`AI/thumbnails/`), and a **privacy warning**: list shots with readable number
plates or strangers' faces (look at the frames; on the first film the owner's own plate was readable in a print and the
thumbnail). Don't blur unless asked.

## Gotchas that cost time on the first film

- Sony MP4s: Final Cut ignores the camera timecode (it's in a missing `M01.XML` sidecar) → assets start at 0.
  Using the timecode made every edit "Invalid edit with no respective media".
- Final Cut **copies** imported stills into the library: give every re-rendered image a new file name or the
  old copy is reused.
- penoftruth draws every accented letter blank → `fonts.drawable()` strips accents (he's fine with that).
- ffmpeg 8: `-/filter_complex <file>` (not `-filter_complex_script`). Whisper/VLM models are local in `models/`.
- Measure loudness and spacing "perceptually": equal pixel gaps looked unequal (descenders); equal cut
  lengths can feel slow: trust the song's energy.
- Lyrics are copyrighted: use vocal *timings* only, never print or store the words.

## Learn

At the end of every movie, diff his final export against your last build and append what you learned to
`~/Dev/movie-making/STYLE.md` (the skill reads it next time). If a rule here turns out wrong, fix it here too.
