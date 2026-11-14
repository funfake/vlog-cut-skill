# vlog-cut

AI-assisted editing for **Final Cut Pro** on a Mac. Point it at a folder of footage, photos and a song:
it analyses everything **locally** (no upload), agrees a story with you, and writes a beat-synced
first cut as an FCPXML you import into Final Cut. After you edit and grade by hand, it layers sound
design, handwritten stamps and a photo recap on top of *your* edit without touching your cut.

It ships as three [Claude Code](https://claude.com/claude-code) skills plus the Python scripts they drive:

| skill | what it does |
|---|---|
| `/vlog-cut-setup` | sets up a Mac: tools, Python packages, local models, fonts, checks |
| `/vlog-cut` | edits a movie: analysis → story → first cut → your Final Cut edit → layers → lessons |
| `/vlog-cut-switch-aspect` | makes the 4:3 (or 16:9) version of a finished edit as a separate project |

The scripts also work on their own, without Claude (see [Using the scripts](#using-the-scripts)).

---

## Requirements (macOS only)

Final Cut Pro is Mac-only, and the local AI models run on Apple's MLX framework, so this is **macOS-only**.

| | needed | why |
|---|---|---|
| Mac | **Apple Silicon** (M1 or later), 16 GB+ RAM recommended | MLX runs the vision and speech models on the GPU |
| macOS | 14 Sonoma or later | MLX, Final Cut Pro 11+ |
| Final Cut Pro | 11 or later (FCPXML 1.13/1.14) | importing the cuts; its FCPXML schema and sound-effects library are used |
| Final Cut sound effects | *Final Cut Pro > Download Additional Content* | card slaps, whooshes, ambiences used for sound design |
| Homebrew | [brew.sh](https://brew.sh) | installs `ffmpeg` and `uv` |
| Xcode Command Line Tools | license accepted | Homebrew refuses to install anything until it is |
| Disk | ~10 GB free | models (~7 GB) + Python environment |
| Network | first setup only | models download from Hugging Face; after that everything is offline |

Nothing else is installed system-wide: Python itself and every Python package (OpenCV, MLX, librosa…)
live in this folder's virtual environment, managed by `uv`.

## Setup

### Quick (recommended)

```bash
git clone https://github.com/funfake/vlog-cut-skill.git ~/Dev/movie-making
~/Dev/movie-making/setup.sh
```

Or, in Claude Code, run `/vlog-cut-setup` and it does the same, explains each step and fixes what fails.
The skills expect the repo at `~/Dev/movie-making`.

`setup.sh` is safe to re-run; it skips whatever is already done:

1. installs `ffmpeg` and `uv` with Homebrew (if missing)
2. `uv sync`: creates `.venv/` with Python 3.12 and all packages
3. downloads the two local models into `models/` (~7 GB, resumable, plain `curl`)
4. links the skills into `~/.claude/skills/`
5. checks Final Cut Pro, its sound-effects library and the handwriting font

### Manual, step by step

**1. Xcode license** (once per Mac; Homebrew fails with *"You have not agreed to the Xcode license"* otherwise):
```bash
xcode-select --install          # if the Command Line Tools aren't installed
sudo xcodebuild -license accept
```

**2. Command-line tools**
```bash
brew install ffmpeg uv
```
`ffmpeg`/`ffprobe` decode the footage and audio (version 8+: note the `-/filter_complex <file>` syntax).
`uv` manages Python. `xmllint` (validation) ships with macOS.

**3. Python environment** (Python 3.12, from `pyproject.toml` / `uv.lock`):
```bash
cd ~/Dev/movie-making
uv sync
```
This installs, among others:

| package | used for |
|---|---|
| `opencv-python-headless` | optical flow (motion, direction, shake), histograms, image ops in `analyze_clips.py` |
| `scenedetect` | cut detection inside clips |
| `librosa`, `soundfile` | beats, bars, sections, energy of the song |
| `mlx-vlm` | local vision model (Qwen3-VL) describing shots |
| `mlx-whisper` | local Whisper: sung-line timings and speech in clips |
| `numpy`, `pillow` | everything image |

About OpenCV: **don't** `brew install opencv` or `pip install opencv-python` system-wide. The project uses the
self-contained `opencv-python-headless` wheel inside `.venv` (no GUI, no Qt, no system libraries), which is
what avoids the usual macOS OpenCV conflicts. If an old `opencv-python` ends up in the venv, see
[Troubleshooting](#troubleshooting).

**4. Local models** (~7 GB; nothing is sent anywhere when they run):
```bash
./scripts/download_model.sh mlx-community/Qwen3-VL-8B-Instruct-4bit models/Qwen3-VL-8B-Instruct-4bit   # 5.8 GB, vision
./scripts/download_model.sh mlx-community/whisper-large-v3-turbo   models/whisper-large-v3-turbo        # 1.5 GB, speech
```

**5. Final Cut Pro sound effects:** in Final Cut, *Final Cut Pro > Download Additional Content*. They land in
`/Library/Audio/Apple Loops/Apple/Final Cut Pro Sound Effects/`.

**6. Handwriting font** (for stamps and the story card): the default is `penoftruth`. Put a `.ttf` in
`~/Library/Fonts/`, or pick any installed handwriting font in the editor (Bradley Hand, Noteworthy and
Chalkboard come with macOS). Some handwriting fonts draw accented letters blank; the scripts detect that
and fall back to the plain letter.

**7. Claude Code skills**
```bash
mkdir -p ~/.claude/skills
ln -sfn ~/Dev/movie-making/skill/vlog-cut       ~/.claude/skills/vlog-cut
ln -sfn ~/Dev/movie-making/skill/vlog-cut-setup ~/.claude/skills/vlog-cut-setup
ln -sfn ~/Dev/movie-making/skill/vlog-cut-switch-aspect ~/.claude/skills/vlog-cut-switch-aspect
```
They're symlinks, so `git pull` updates them.

### Check the install

```bash
cd ~/Dev/movie-making
ffmpeg -version | head -1
uv run python -c "import cv2, librosa, mlx.core as mx, mlx_vlm, mlx_whisper; print('cv2', cv2.__version__, '| mlx', mx.__version__, '| ok')"
ls models/*/config.json
```

## Troubleshooting

| symptom | fix |
|---|---|
| `brew`: *You have not agreed to the Xcode license* | `sudo xcodebuild -license accept` |
| `ImportError` / crash on `import cv2`, or Qt/`cocoa` plugin errors | another OpenCV is shadowing the headless one: `uv pip uninstall opencv-python opencv-contrib-python && uv sync --reinstall-package opencv-python-headless` |
| `uv` installs an x86_64 Python, MLX fails to import | you're in a Rosetta (Intel) terminal: open a native one (`arch` should print `arm64`), `rm -rf .venv && uv sync` |
| `Unrecognized option 'filter_complex_script'` | ffmpeg 8 renamed it; the scripts already use `-/filter_complex`: update the repo |
| Final Cut: *Invalid edit with no respective media* | footage timecode mismatch. The scripts start clips at 0 because Final Cut ignores Sony MP4 timecode when the `M01.XML` sidecars aren't copied. If you keep the sidecars, set `"use_camera_timecode": true` in the movie's settings |
| a re-rendered image doesn't change in Final Cut | Final Cut copied the old file into the library; the editor always writes new file names: re-import the new FCPXML |
| the model download stops | re-run the same command; `curl -C -` resumes |
| stamps show gaps instead of accents | the font has blank accent glyphs; the scripts strip accents automatically, or pick another font |

## Using it with Claude Code

1. Put the movie in its own folder: `MOVIES/<name>/SHOTS` (video), `PICS` (photos), and the song.
2. In Claude Code: `/vlog-cut` (or just "let's edit my new movie in …"). It asks you a few questions about the
   day, shows the story, music edit and shot list for your OK, then builds the first cut.
3. Import it in Final Cut (File > Import > XML…), edit and grade, export as `.fcpxmld` into the movie's
   `AI/fcpxml/`, and hand it back: it layers sound, stamps and the recap on top, and learns from your changes
   (`STYLE.md`).

## Using the scripts

Each movie has a settings file: copy `projects/example.json` to `projects/<movie>.json`, fill in the paths
and a one-line `context`, then prefix commands with `VLOG_PROJECT=projects/<movie>.json`.

| step | script | output |
|---|---|---|
| measure clips | `analyze_clips.py` | motion, direction, shake, light, warmth, sound per clip; keyframes; contact sheets |
| describe shots | `describe_clips.py` | local vision model: setting, landmark, shot type, light, mood, beauty/energy |
| shot log | `shotlog.py`, `overview.py` | one line per keyframe; one frame per clip |
| music | `analyze_music.py` | tempo, beats, bars, sections, energy, hits |
| vocals / speech | `transcribe_music.py`, `transcribe_clips.py` | sung-line and spoken-line timings (lyrics are not stored) |
| first cut | `build_fcpxml.py plan.json --out name.fcpxml` | beat-synced FCPXML, validated against Final Cut's own schema; refuses music edits that cut vocals |
| recap & stamps | `render_recap_styles.py`, `render_stamps.py` | polaroid / film strip / scrapbook recaps, notebook card, handwritten stamps |
| layering | `augment_fcpxml.py export.fcpxmld layers.json --out name.fcpxml` | audio levels, ramps, sound effects, stamps, stills on top of your edit (cut and grade untouched) |
| checks | `mixdown.py`, `diff_fcpxml.py`, `timeline_summary.py` | loudness (target −14 LUFS, ≤ −1 dBTP); what changed between two timelines |
| other aspect | `switch_aspect.py final.fcpxmld --to 4:3`, `reframe.py new.fcpxml --shot C1137=+240` | a separate 4:3 (or 16:9) project: frame, Fill crop, recap/card/stamps re-rendered; slide shots whose subject the crop cuts |
| publishing | `video_chapters.py final.fcpxmld` | description timestamps from the stamps in your final edit (title/description go in `AI/desc/`) |

Plan and layer formats: `examples/` and `skill/vlog-cut/references/commands.md`. Scripts skip finished work
(`--force` to redo) and take `--only <clip>`.

### Editor

```bash
uv run scripts/editor.py      # http://localhost:8765
```
Live preview of the story card (text, font, sizes, line height, spacing, width), the recap (style, layout,
photos and captions) and the stamps (text, timing, previewed over the real footage). **Build FCPXML** renders
everything with unique file names and layers it onto the Final Cut export you pick.

## Where files go

| what | where | in git? |
|---|---|---|
| FCPXMLs, stills Final Cut links to, thumbnails, previews, mixes | `<movie folder>/AI/{fcpxml,stills,thumbnails,previews,audio,desc}/` | no |
| analysis cache (frames, shot logs, music/vocal maps) | `work/<movie>/` | no |
| per-movie settings, edit plans, editor state | `projects/<movie>.json`, `edit/` | no |
| models, Python environment | `models/`, `.venv/` | no |
| Final Cut's FCPXML schema | copied from your Final Cut Pro into `vendor/` on first use | no (Apple's file) |
| scripts, editor, skills, examples, `STYLE.md` | this repo | yes |

`STYLE.md` is the editing taste the workflow learns from your final edits; it's meant to evolve.

## Notes

- Footage assumptions: 1080p, 29.97 fps (Sony XAVC S). Other frame rates: `FPS_NUM/FPS_DEN` in `build_fcpxml.py`.
- Everything runs offline after setup. Lyrics from transcription are never stored or printed, only their timings.
- Before publishing a film, check the privacy warning the skill gives (readable number plates, strangers' faces).
