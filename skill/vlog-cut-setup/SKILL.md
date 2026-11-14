---
name: vlog-cut-setup
description: >-
  Set up or repair the vlog-cut video-editing toolkit on a Mac: Homebrew tools (ffmpeg, uv), the Python
  environment (OpenCV, librosa, MLX), the local vision and Whisper models, Final Cut Pro sound effects,
  handwriting fonts, and the Claude skills. Use this whenever the user wants to install vlog-cut on a new or
  second Mac/account, says the editing scripts or models don't work, gets ffmpeg/OpenCV/MLX/uv/Homebrew errors
  with ~/Dev/movie-making, or before a first /vlog-cut run on a machine where it hasn't been verified.
---

# vlog-cut-setup

Gets a Mac ready for `/vlog-cut`. The repo lives at `~/Dev/movie-making` (public:
`https://github.com/funfake/vlog-cut-skill`). Its `setup.sh` does the work; your job is to run it, read what it
reports, fix what failed, and finish with a verified install. The README has the full manual and a
troubleshooting table: read `~/Dev/movie-making/README.md` when something fails.

macOS + Apple Silicon only: Final Cut Pro is Mac-only and the models run on MLX. If `uname -m` isn't `arm64`
or it's not macOS, say so plainly and stop: don't try to make it work on Intel/Rosetta or Linux.

## Steps

1. **Repo.** If `~/Dev/movie-making` doesn't exist, clone it there (ask before cloning elsewhere: the skills
   assume that path). If it exists, `git status` first; don't pull over the user's local changes without asking.

2. **Prerequisites the script can't do for them**: check, and ask the user to act when needed:
   - Homebrew (`brew`); if missing, point them to https://brew.sh (it needs their password).
   - Xcode license: if `brew` prints *You have not agreed to the Xcode license*, the user must run
     `sudo xcodebuild -license accept` themselves (it needs their password and accepts Apple's terms: never
     run it for them without their explicit go-ahead; offering to type it into their terminal is fine).
   - Final Cut Pro installed, and its sound effects (*Final Cut Pro > Download Additional Content*).
   - Free disk ~10 GB (`df -h ~`).

3. **Run `~/Dev/movie-making/setup.sh`** in the background (the models are ~7 GB) and report progress. It installs
   ffmpeg and uv, runs `uv sync`, downloads the two models, links both skills, and checks Final Cut, its sound
   effects and the font. It is idempotent: re-run it after fixing anything.

4. **Verify**: all three must pass before you say it's ready:
   ```bash
   cd ~/Dev/movie-making
   ffmpeg -version | head -1
   uv run python -c "import cv2, librosa, mlx.core as mx, mlx_vlm, mlx_whisper; print('cv2', cv2.__version__, 'mlx', mx.__version__)"
   ls models/Qwen3-VL-8B-Instruct-4bit/config.json models/whisper-large-v3-turbo/config.json
   ```
   Optionally a real smoke test: build one FCPXML from `examples/plan.example.json` only if the user has footage
   configured; otherwise the import check is enough.

5. **Font.** The default handwriting font is `penoftruth` (`~/Library/Fonts/penoftruth.ttf`). If it's missing, ask
   the user to copy it from their other Mac or pick another installed handwriting font in the editor (Bradley
   Hand, Noteworthy, Chalkboard come with macOS). Don't download fonts from random sites.

6. **Hand-off.** Tell the user it's ready and how to start: copy `projects/example.json` to
   `projects/<movie>.json` (or let `/vlog-cut` do it) and run `/vlog-cut` with the movie folder.

## Common failures (details in the README troubleshooting table)

- `import cv2` fails / Qt plugin errors → another OpenCV shadows the headless wheel:
  `uv pip uninstall opencv-python opencv-contrib-python && uv sync --reinstall-package opencv-python-headless`.
  Never `brew install opencv` for this project.
- MLX import error / x86_64 Python → Rosetta terminal: `arch` must say `arm64`; then `rm -rf .venv && uv sync`.
- Model download interrupted → re-run; `download_model.sh` resumes with `curl -C -`.
- `~/.claude/skills/vlog-cut` exists as a real folder (old copy) → ask before replacing it with the symlink.
- Per-movie files (`projects/*.json`, `edit/`, `work/`) are not in git: on a second machine they start empty.
  Movie outputs live next to the footage (`<movie>/AI/`), so plugging in the same drive brings them along.
