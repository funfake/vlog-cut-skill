---
name: vlog-cut-switch-aspect
description: >-
  Create the other aspect-ratio version (16:9 to 4:3, or 4:3 to 16:9) of a finished vlog-cut / Final Cut Pro
  edit as a separate project, without touching the original. Use this whenever the user wants a 4:3 (or 16:9)
  variant, a square-ish or retro-format version, "the other format", or when a movie's settings ask for both
  aspects, even if they don't name the command.
---

# vlog-cut-switch-aspect

Makes a new FCPXML in the other aspect ratio from a finished edit (normally his hand-edited `.fcpxmld` export in
`<movie>/AI/fcpxml/`). Tool: `~/Dev/movie-making/scripts/switch_aspect.py`. The source edit is **read only**: never
write into it, never re-use its project name, never overwrite its images.

## Steps

1. **Pick the source.** The latest export he edited by hand (`*.fcpxmld` in `AI/fcpxml/`, newest first). If
   unsure which one is final, ask. The movie's drive must be mounted (`ls /Volumes`); if the script says
   "Movie folder not found", ask him to plug it in.
2. **Check the editor settings** (`edit/editor-state.json`) belong to this movie: they hold the recap photos,
   the card text and the stamp texts that get re-rendered. Wrong movie → stop and ask.
3. **Run it** (with the movie's `VLOG_PROJECT`):
   ```bash
   uv run scripts/switch_aspect.py "<source>.fcpxmld" --to 4:3 --project "<name> 4-3"
   ```
   It keeps every cut, the grade (adjustment clips), the audio mix and sound design; it changes the frame
   (4:3 = 1440x1080), sets footage to Fill (center crop), and re-renders the recap, the story card and the
   stamps for the new frame with new file names.
4. **Verify before telling him it's done:**
   - the source file's checksum is unchanged (take it before running);
   - the new file passes the DTD check, shows the new frame size, same number of cuts and same timings;
   - every image and sound it references exists.
5. **Show him** before/after: the recap's final frame and a few stamp frames in the new aspect, plus 2 or 3
   footage frames cropped to 4:3 (center crop of the keyframes in `work/<movie>/frames/`). Point out shots where
   the crop cuts the subject (car, landmark, a person at the edge) and suggest reframing them in Final Cut
   (*Transform > Position X* on that clip). If he asks you to fix them: check the subject's position at the
   start, middle and end of the shot (it often drifts when the camera pans), then
   `uv run scripts/reframe.py "<new>.fcpxml" --shot C1137=+240` (px of the 1920-wide source; + shows more of
   the right side, max ±240 for 16:9 -> 4:3). Only on the generated file, never on his export. Show before/after.
6. Import: File > Import > XML; it appears as its own project next to the 16:9 one.

## Notes

- 4:3 removes 240 px (12.5 %) on each side of a 1920x1080 frame. Stamps sit 96 px from the left edge, so they
  must be re-rendered (the script does), not just cropped.
- The polaroid recap and scrapbook layouts scale to the frame width; the film-strip style is 16:9-only for now.
- Thumbnails stay 16:9 (YouTube); make a 4:3 one only if he asks.
