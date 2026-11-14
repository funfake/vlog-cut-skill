# Editing style (learned on "driving in paris", Nov 2026)

What worked and what was rejected, so the next video starts from here.

## Story first
- Every shot must earn its place in a one-line story; cut near-duplicates
  (same subject, same angle) even if they look good. One shot per story beat.
- Give context early: after a short opening (the garage), a fast riffle of
  printed photos + a handwritten card telling the story, then the film.
- Payoff structure works: set something up early (hazy Eiffel Tower) and pay it
  off at the end (sparkling Eiffel Tower).

## Pacing
- Short. ~1 minute for ~12 min of footage. Shorten the music rather than pad.
- Follow the song: slow in quiet sections, fast in loud/instrumental ones
  (slow / fast / slow / fast). Verses with vocals: one shot per sung line (~4 beats).
  Instrumental drops: 2-beat cuts.
- Openings must move: no long establishing holds. Garage shots ~1-2 s each.
- Photo prints arrive very fast (2-3 frames each, ~0.6 s for 8). The card that
  follows is held only long enough to read (~2.5 s).

## Cuts and transitions
- Hard cuts only. No cross-dissolves, no slow Ken Burns zooms.
- Cut on movement; cut 1 frame before the beat.
- Never start on black/dark frames (check brightness before the in-point).

## Music
- Never cut the vocals mid-line: splices and fades only in gaps between sung
  lines (scripts/transcribe_music.py + the builder's vocal check).
- Splices must sound seamless: same phrase position, similar sound on both
  sides; hide them under a picture cut. Prefer the song's own drum entrance.

## Look and graphics
- Stills: white-bordered prints on a textured near-black surface (not wood).
- Handwriting: penoftruth (felt pen). Bradley Hand was too formal.
- Sound on graphics: a short card slap per print (Final Cut "Cards.caf" hits).
- Color: done by hand in Final Cut with Custom LUT + Color Adjustments on
  adjustment clips; don't auto-grade over it.

## Files
- All outputs go in the movie's own folder `<movie folder>/AI/`, sorted by kind (fcpxml/, stills/,
  thumbnails/, previews/, audio/, desc/),
  never in this tool folder. Editor builds are named after the project.

## Learned from the final hand edit (v22 -> v23)
- Stamps last the whole shot they label (end on the cut), not a fixed 1.8-2 s.
- Skip lead-ins, not just black frames: C1138 started 1 s later than the brightness check allowed.
- Final polish is frame-level (in-points, music splice by 1 frame); the structure held.

## Writing
- Never use em dashes or en dashes in any text (titles, descriptions, cards, stamps). Commas, colons, new lines.
- YouTube timestamps: `mm:ss text`, one per line, starting at `00:00`, no `·` or other separators in the text.
