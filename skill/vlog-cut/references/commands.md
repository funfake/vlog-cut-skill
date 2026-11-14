# vlog-cut: commands and file formats

All commands run from `~/Dev/movie-making` with `VLOG_PROJECT=projects/<slug>.json` set.
Python deps via `uv` (never npm). Models: `models/Qwen3-VL-8B-Instruct-4bit`, `models/whisper-large-v3-turbo`
(download with `scripts/download_model.sh <hf-repo> <dir>` if missing: runs with plain curl).

## Contents
1. Analysis scripts
2. Edit plan format (first cut)
3. Layers format (on top of his export)
4. Editor
5. Verification snippets

## 1. Analysis scripts

| script | output (work/<movie>/) | notes |
|---|---|---|
| `analyze_clips.py [--jobs 8]` | `clips/*.json`, `frames/`, `sheets/` | motion, direction (pan_x), forward travel, shake, brightness, warmth, sound dB @4 fps; skips done clips |
| `describe_clips.py` | `descriptions/*.json` | local VLM per 2 s keyframe; ~15 min for 350 frames: background it |
| `shotlog.py > shotlog.txt` | one line per keyframe | read this + contact sheets to plan |
| `overview.py` | `overview.jpg` | one frame per clip with clock time |
| `analyze_music.py` | `music.json`, `music.png` | tempo, beats, downbeat phase, sections (low/mid/high), hits |
| `transcribe_music.py` | `vocals.json` | sung-line timings only (no lyrics stored) |
| `transcribe_clips.py` | `speech/*.json` | spoken lines in clips; protect them when cutting |

Clock time of a shot = `info.creation_time` (Sony writes local time tagged Z) + in-point.
Picking a splice: score bar-line pairs by audio similarity on both sides (chroma+MFCC+RMS), require same
phrase position (`(a-b) % 16 == 0`) and both points in vocal gaps; the first film went from 9.7 to 0.42.

## 2. Edit plan format: `edit/<slug>-vN.json` → `build_fcpxml.py`

```json
{
  "project": "my movie - AI cut v1",
  "music": [{"from_beat": 16, "to_beat": 32},
            {"from_beat": 116, "to_beat": 168, "tail": 4.0, "fade_out": 4.0}],
  "music_volume_db": 0, "clip_volume_db": -22,
  "cut_early_frames": 1,          // cut 1 frame before the beat
  "cut_on_motion": 0.75,          // nudge in-points ±s so cuts land on movement; "fixed": true opts out
  "sfx": {"card": {"file": "/Library/Audio/Apple Loops/Apple/Final Cut Pro Sound Effects/Sports & Leisure/Cards.caf",
                   "hits": [1.02, 3.78, 4.34, 3.18, 4.67], "dur": 0.2, "db": -2}},
  "segments": [
    {"clip": "C1103", "in": 58.5, "beats": 2, "volume_db": -8, "note": "why this shot"},
    {"photo": "recap_01", "beats": 0.125, "sfx": "card"},       // images: PICS name or a rendered still name
    {"clip": "C1144", "in": 0.2, "until_end": true, "fixed": true},
    {"gap": true, "until_end": true}
  ]
}
```
`uv run scripts/build_fcpxml.py edit/x.json --out name.fcpxml --event "event name"` → `<movie>/AI/fcpxml/`.
Fractional beats are fine (riffles). Transitions exist (`"transition": 0.6`) but he wants hard cuts.

Recap / card images: `render_recap_styles.py polaroid-note --photos ... --captions 17h39 ... --title "title" "line" ... "08.11.26"`
(styles: polaroid-note, polaroid, filmstrip, scrapbook) → `AI/stills/`. Stamps: `render_stamps.py "17h39 · au parking" ...`.

## 3. Layers format: on top of his `.fcpxmld` → `augment_fcpxml.py`

```json
{
  "project": "… v23",
  "gain": {"music": -3, "sfx card": 3, "spine:0-2": 9},          // relative dB (connected by name prefix, spine by index)
  "mute": ["spine:12-34"],                                         // -96 dB
  "volume_keys": {"spine:0": [[0.0, -30], [1.2, -8]]},            // ramps, s from clip start
  "fades": {"music 1": {"in": 0.5}},                               // connected clip fades, keeps its keyframes
  "audio": [{"name": "whoosh into the drop", "file": ".../Whoosh 13.caf", "at": 25.87, "src": 0, "dur": 1.32,
             "db": -8, "fade_in": 0, "fade_out": 0.25, "lane": -4}],
  "replace_stills": ["/abs/AI/stills/x_01.jpg", "..."],           // first N stills of the timeline, in order
  "remove_overlays": "stamp",                                      // drop old stamps first
  "overlays": [{"name": "stamp 17h39", "file": "/abs/AI/stills/stamp_01.png", "at": 0.0, "dur": 1.2, "lane": 2}]
}
```
`uv run scripts/augment_fcpxml.py "<export>.fcpxmld" edit/layers.json --out "name.fcpxml"` → `AI/fcpxml/`.
An example audio mix is in `examples/audio-mix.json` (Final Cut library sounds that worked:
Cards.caf hits, Whoosh 13 into a drop, Auto Vintage Sports Pull Away for an engine launch, Traffic City 08 ambience).

## 4. Editor

`uv run scripts/editor.py` → http://localhost:8765. State: `edit/editor-state.json` (card text/sizes/rule/gap/width,
style, seed, photos+captions, stamps text/at/dur, export to build on, audio layers file, project name).
Build writes unique stills + a layers file + `AI/fcpxml/<project>.fcpxml`. It builds by stills order, so it
survives his re-exports. If you edit the state file while the page is open, reload the page afterwards
(the page posts its in-memory state on every change). Restart the server after editing editor.py.

## 5. Verification snippets

- Diff his edit: `uv run scripts/diff_fcpxml.py base.fcpxml export.fcpxmld`
- Other aspect ratio (new project, source untouched): `uv run scripts/switch_aspect.py "<final>.fcpxmld" --to 4:3`
- Description timestamps from his final edit: `uv run scripts/video_chapters.py "<final>.fcpxmld"` (`--json` for data);
  text files go to `<movie>/AI/desc/` (`out_path(cfg, "description.txt")` routes .txt/.md there)
- Loudness: `uv run scripts/mixdown.py file.fcpxml --out mix.wav` (prints music / camera / sfx / full mix)
- His cut + grade untouched: compare spine `(offset,start,duration)` and all `filter-video` elements between
  his export and your output: must be identical.
- Media resolve: every `media-rep src` path exists (stills moved → rewrite `file://` URLs).
