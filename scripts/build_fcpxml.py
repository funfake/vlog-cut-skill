"""Turn an edit plan (JSON) into an FCPXML event for Final Cut Pro.

The event holds:
  * every source clip, with keyword ranges and favourites from the analysis (browse by
    "night", "pov_windshield", "landmark"... even if you ignore the cut),
  * the photos and the music,
  * one project per plan: the cut on the music, with a marker explaining each choice.

Source media is referenced in place (never copied or modified).

Plan format (edit/<name>.json):
{
  "project": "driving in paris - cut v1",
  "music_in": 0.0,                 # where in the song the timeline starts (s)
  "music_volume_db": 0,
  "clip_volume_db": -18,           # default level of camera sound under the music
  "music": [{"from_beat": 0, "to_beat": 32},                      # optional music edit: song pieces
            {"from_beat": 96, "to_beat": 252, "tail": 3.6, "fade_out": 4.8}],  # spliced on bar lines
  "cut_early_frames": 1,           # cut N frames before the beat (reads as "on" the beat)
  "cut_on_motion": 0.75,           # nudge in-points up to N s so cuts land on movement ("fixed": true opts out)
  "segments": [
    {"clip": "C1102", "in": 3.2, "beats": 8, "note": "why", "volume_db": -6},
    {"photo": "DSC02270", "beats": 4, "zoom": [1.0, 1.08], "note": "..."},
    {"clip": "C1143", "in": 2.0, "until_end": true, "note": "last shot runs to the end of the song"},
    {"clip": "C1120", "in": 4, "dur": 3.0, "note": "seconds instead of beats"},
    {"clip": "...", "transition": 1.0},         # cross-dissolve INTO this segment (seconds)
    {"gap": true, "until_end": true, "transition": 1.5}   # fade to black
  ]
}
Cuts land on detected beats from music.json (or on a fixed duration when "dur" is used).

Usage: uv run scripts/build_fcpxml.py edit/v1.json [edit/v2.json ...] --out work/.../driving-in-paris.fcpxml
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_project, out_path  # noqa: E402

FPS_NUM, FPS_DEN = 30000, 1001                 # 29.97 fps
FRAME = Fraction(FPS_DEN, FPS_NUM)
DISSOLVE_UID = "FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265"
TRUSTED_LANDMARKS = ("Eiffel Tower", "Arc de Triomphe", "Louvre")
# Copied from Final Cut Pro.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/
# (xmllint can't load a DTD from a path with spaces)
DTD = ROOT / "vendor" / "FCPXMLv1_13.dtd"


def frames(sec: float | Fraction) -> int:
    return int(round(Fraction(sec) / FRAME))


def T(n_frames: int) -> str:
    """Rational FCPXML time for a whole number of frames."""
    if n_frames == 0:
        return "0s"
    v = Fraction(n_frames * FPS_DEN, FPS_NUM)
    return f"{v.numerator}/{v.denominator}s" if v.denominator != 1 else f"{v.numerator}s"


def url(path: str) -> str:
    return "file://" + quote(path)


def tc_frames(tc: str | None) -> int:
    if not tc:
        return 0
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * 30 + f      # NDF counting at 30 for 29.97


def a(**kw) -> str:
    return " ".join(f"{k.rstrip('_')}={quoteattr(str(v))}" for k, v in kw.items() if v is not None)


class Builder:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        w = cfg["work"]
        self.clips = {p.stem: json.loads(p.read_text()) for p in sorted((w / "clips").glob("*.json"))}
        self.desc = {p.stem: json.loads(p.read_text()) for p in sorted((w / "descriptions").glob("*.json"))}
        self.music = json.loads((w / "music.json").read_text())
        self.res: list[str] = []
        self.ids: dict[str, str] = {}
        self.photo_ids: dict[str, str] = {}

    # ---------- resources ----------
    def resources(self, photos: set[str]) -> None:
        self.res.append(f'<format id="r1" name="FFVideoFormat1080p2997" frameDuration="{T(1)}" '
                        f'width="1920" height="1080" colorSpace="1-1-1 (Rec. 709)"/>')
        self.res.append('<format id="r2" name="FFVideoFormatRateUndefined" width="5472" height="3080" '
                        'colorSpace="1-13-1"/>')
        self.res.append(f'<effect id="fxDissolve" name="Cross Dissolve" uid="{DISSOLVE_UID}"/>')
        for i, (name, c) in enumerate(self.clips.items(), 1):
            info = c["info"]
            rid = f"a{i}"
            self.ids[name] = rid
            # Final Cut ignores the Sony timecode in these MP4s (it lives in the camera's
            # M01.XML sidecar, which isn't copied) and starts every clip at 0. Match that,
            # or every edit points outside the media ("Invalid edit with no respective media").
            start = tc_frames(info.get("timecode")) if self.cfg.get("use_camera_timecode") else 0
            c["_start"] = start
            c["_dur"] = frames(info["duration"])
            self.res.append(
                f'<asset {a(id=rid, name=name, start=T(start), duration=T(c["_dur"]), hasVideo=1, format="r1", hasAudio=1, videoSources=1, audioSources=1, audioChannels=info.get("audio_channels", 2), audioRate=info.get("audio_rate", 48000))}>'
                f'<media-rep kind="original-media" src={quoteattr(url(info["file"]))}/></asset>')
        m = self.music
        self.music_dur = frames(m["duration"])
        self.res.append(
            f'<asset {a(id="m1", name=Path(m["file"]).stem, start="0s", duration=T(self.music_dur), hasAudio=1, audioSources=1, audioChannels=2, audioRate=44100)}>'
            f'<media-rep kind="original-media" src={quoteattr(url(m["file"]))}/></asset>')
        pics = Path(self.cfg["pics_dir"])
        stills = self.cfg["stills"]          # rendered images (e.g. render_table_stills.py)
        still_formats: dict[tuple[int, int], str] = {}
        for j, p in enumerate(sorted(photos), 1):
            rid = f"p{j}"
            self.photo_ids[p] = rid
            f = next(pics.glob(p + ".*"), None)
            fmt = "r2"
            if f is None:
                f = next(stills.glob(p + ".*"))
                from PIL import Image
                size = Image.open(f).size
                if size not in still_formats:
                    still_formats[size] = f"r{3 + len(still_formats)}"
                    self.res.insert(2, f'<format id="{still_formats[size]}" name="FFVideoFormatRateUndefined" '
                                       f'width="{size[0]}" height="{size[1]}" colorSpace="1-13-1"/>')
                fmt = still_formats[size]
            self.res.append(f'<asset {a(id=rid, name=p, start="0s", duration="0s", hasVideo=1, format=fmt, videoSources=1)}>'
                            f'<media-rep kind="original-media" src={quoteattr(url(str(f)))}/></asset>')

    # ---------- browser clips with keywords ----------
    def event_clips(self) -> list[str]:
        out = []
        for name, c in self.clips.items():
            start, dur = c["_start"], c["_dur"]
            inner = []
            frames_desc = self.desc.get(name, {}).get("frames", [])
            if frames_desc:
                kw = Counter()
                for fd in frames_desc:
                    for key in ("setting", "light", "shot_type"):
                        v = fd.get(key)
                        if isinstance(v, str) and v and v != "other":
                            kw[v.split("|")[0].strip()] += 1
                    lm = str(fd.get("landmark") or "")
                    # the model guesses landmark names; only keep ones it reliably recognises
                    if any(k in lm for k in TRUSTED_LANDMARKS):
                        kw[f"landmark: {next(k for k in TRUSTED_LANDMARKS if k in lm)}"] += 2
                # only labels the model gave on at least half the frames (single-frame guesses are noisy)
                keep = [k for k, n in kw.most_common(4) if n >= max(1, (len(frames_desc) + 1) // 2)]
                if keep:
                    inner.append(f'<keyword {a(start=T(start), duration=T(dur), value=", ".join(keep))}/>')
                # favourites: frames the model scored 8+, as ~2 s ranges
                for fd in frames_desc:
                    try:
                        b = float(fd.get("beauty", 0))
                    except (TypeError, ValueError):
                        b = 0
                    if b >= 8:
                        s = start + frames(max(0.0, fd["t"] - 1.0))
                        d = min(frames(2.0), start + dur - s)
                        if d > 0:
                            inner.append(f'<rating {a(start=T(s), duration=T(d), value="favorite", note=fd.get("subject"))}/>')
            summ = c["summary"]
            if summ.get("shake") and summ["shake"] > 3.5:
                inner.append(f'<keyword {a(start=T(start), duration=T(dur), value="shaky")}/>')
            out.append(f'<asset-clip {a(ref=self.ids[name], name=name, start=T(start), duration=T(dur), format="r1", tcFormat="NDF")}>'
                       + "".join(inner) + "</asset-clip>")
        return out

    # ---------- the cut ----------
    def _music_pieces(self, plan: dict):
        """Song pieces laid end to end on the timeline (a music edit), plus the beat grid.

        plan["music"] = [{"from_beat": 0, "to_beat": 32}, {"from_beat": 96, "to_beat": 252,
                          "tail": 3.6, "fade_out": 4.8}]
        Without it, the song plays from plan["music_in"] (seconds) to the end.
        """
        beats = [b["t"] for b in self.music["beats"]]
        song_len = self.music["duration"]
        spec = plan.get("music") or [{"from_s": plan.get("music_in", 0.0)}]
        pieces, grid, pos = [], [], 0.0
        for sp in spec:
            src0 = beats[sp["from_beat"]] if "from_beat" in sp else sp.get("from_s", 0.0)
            if "to_beat" in sp:
                src1 = beats[sp["to_beat"]] if sp["to_beat"] < len(beats) else song_len
            else:
                src1 = song_len
            tail = float(sp.get("tail", 0.0))
            src1_play = min(song_len, src1 + tail)
            grid += [pos + (t - src0) for t in beats if src0 - 1e-6 <= t < src1 - 1e-6]
            pieces.append({"src0": src0, "src1": src1_play, "pos": pos,
                           "fade_out": float(sp.get("fade_out", 0.0)), "fade_in": float(sp.get("fade_in", 0.0))})
            pos += src1_play - src0
        if "to_beat" in spec[-1]:
            # the closing bar line, so a segment can end exactly where the last piece's beats stop
            p = pieces[-1]
            grid.append(p["pos"] + (beats[spec[-1]["to_beat"]] if spec[-1]["to_beat"] < len(beats) else song_len) - p["src0"])
        return pieces, grid, pos

    def _best_in(self, name: str, want_in: float, dur_s: float, window: float) -> float:
        """Cut on action: nudge the in-point (within +/-window) so both cuts land on movement."""
        c = self.clips[name]
        samples, clip_len = c["samples"], c["info"]["duration"]
        if not samples or window <= 0:
            return want_in

        def motion_at(t):
            s = min(samples, key=lambda x: abs(x["t"] - t))
            return (s.get("motion") or 0) - 0.5 * (s.get("shake") or 0)

        best, best_score = want_in, None
        step = 1 / max(1.0, c.get("sample_fps", 4))
        k = -window
        while k <= window + 1e-9:
            t_in = want_in + k
            if 0 <= t_in and t_in + dur_s <= clip_len - 0.05:
                # favour movement at the outgoing cut, then at the incoming one, and stay close to the plan
                score = motion_at(t_in + dur_s) + 0.6 * motion_at(t_in) - 0.8 * abs(k)
                if best_score is None or score > best_score:
                    best, best_score = t_in, score
            k += step
        return round(best, 3)

    def _check_vocals(self, pieces: list[dict]) -> None:
        """Refuse music edits that start, splice or fade inside a sung line (vocals.json)."""
        vf = self.cfg["work"] / "vocals.json"
        if not vf.exists():
            return
        lines = [(ln["start"], ln["end"]) for ln in json.loads(vf.read_text())["lines"]]
        problems = []
        for n, pc in enumerate(pieces):
            checks = [("starts", pc["src0"], pc["src0"])]
            end_zone = pc["src1"] - (pc["fade_out"] or 0.05)
            checks.append(("ends/fades", end_zone, pc["src1"]))
            for what, t0, t1 in checks:
                for s, e in lines:
                    if t0 < e + 0.1 and t1 > s - 0.1:
                        problems.append(f"music piece {n + 1} {what} at {t0:.2f}-{t1:.2f}s inside a sung line ({s:.2f}-{e:.2f}s)")
        if problems:
            raise SystemExit("Music edit would cut the vocals:\n  " + "\n  ".join(problems))

    def project(self, plan: dict) -> str:
        pieces, tl_beats, song_end = self._music_pieces(plan)
        self._check_vocals(pieces)
        early = int(plan.get("cut_early_frames", 0))
        nudge = float(plan.get("cut_on_motion", 0.0))
        clip_vol = plan.get("clip_volume_db", -18)

        cursor_s, beat_idx, offset_f = 0.0, 0, 0
        elems = []   # dicts: offset, dur, local_start, open, inner, close
        segs = plan["segments"]
        for i, seg in enumerate(segs):
            last = i == len(segs) - 1
            if seg.get("until_end"):
                end_s = song_end
            elif "beats" in seg:
                # beat position may be fractional (half-beats): interpolate inside the grid
                while beat_idx < len(tl_beats) and tl_beats[beat_idx] < cursor_s - 0.05:
                    beat_idx += 1
                pos = float(beat_idx)
                if beat_idx > 0 and beat_idx < len(tl_beats) and tl_beats[beat_idx] - cursor_s > 0.05:
                    lo, hi = tl_beats[beat_idx - 1], tl_beats[beat_idx]
                    pos = beat_idx - 1 + (cursor_s - lo) / (hi - lo)
                target = pos + float(seg["beats"])
                k = int(target)
                if k + 1 < len(tl_beats):
                    end_s = tl_beats[k] + (target - k) * (tl_beats[k + 1] - tl_beats[k])
                elif k < len(tl_beats) and abs(target - k) < 1e-6:
                    end_s = tl_beats[k]
                else:
                    end_s = song_end
                beat_idx = k if abs(target - k) < 1e-6 else k + 1
            else:
                end_s = cursor_s + float(seg["dur"])
            end_f = frames(end_s) - (0 if last or seg.get("until_end") else early)
            dur_f = end_f - offset_f
            if dur_f <= 0:
                raise SystemExit(f"segment has no length: {seg}")
            note = seg.get("note", "")
            trans = seg.get("transition")
            if trans and elems:
                td = frames(float(trans))
                elems.append({"transition": f'<transition {a(name="Cross Dissolve", offset=T(offset_f - td // 2), duration=T(td))}>'
                                            f'<filter-video ref="fxDissolve" name="Cross Dissolve"/></transition>'})

            if seg.get("gap"):
                elems.append({"offset": offset_f, "dur": dur_f, "local": frames(3600), "tag": "gap",
                              "attrs": a(name="Gap", offset=T(offset_f), start="3600s", duration=T(dur_f)), "inner": []})
            elif "clip" in seg:
                name = seg["clip"]
                c = self.clips[name]
                want_in = float(seg.get("in", 0))
                t_in = want_in if seg.get("fixed") else self._best_in(name, want_in, dur_f * float(FRAME), nudge)
                src_start = c["_start"] + frames(t_in)
                if dur_f > c["_start"] + c["_dur"] - src_start:
                    raise SystemExit(f"{name}: needs {dur_f} frames from {t_in}s but the clip is too short")
                inner = []
                if seg.get("zoom"):
                    inner.append(self._zoom(seg["zoom"], src_start, dur_f))
                inner.append(f'<adjust-volume amount="{seg.get("volume_db", clip_vol)}dB"/>')
                if seg.get("sfx"):
                    inner.append(self._sfx(plan, seg, src_start))
                if note:
                    if abs(t_in - want_in) > 0.01:
                        note += f" [in-point nudged {t_in - want_in:+.2f}s to cut on movement]"
                    inner.append(f'<marker {a(start=T(src_start), duration=T(1), value=note[:300])}/>')
                elems.append({"offset": offset_f, "dur": dur_f, "local": src_start, "tag": "asset-clip",
                              "attrs": a(ref=self.ids[name], name=name, offset=T(offset_f), start=T(src_start), duration=T(dur_f), format="r1", tcFormat="NDF"),
                              "inner": inner})
            else:
                inner = ['<adjust-conform type="fill"/>']
                if seg.get("zoom"):
                    inner.append(self._zoom(seg["zoom"], 0, dur_f, pos=seg.get("pan")))
                if seg.get("sfx"):
                    inner.append(self._sfx(plan, seg, 0))
                if note:
                    inner.append(f'<marker {a(start="0s", duration=T(1), value=note[:300])}/>')
                elems.append({"offset": offset_f, "dur": dur_f, "local": 0, "tag": "video",
                              "attrs": a(ref=self.photo_ids[seg["photo"]], name=seg["photo"], offset=T(offset_f), start="0s", duration=T(dur_f)),
                              "inner": inner})
            offset_f = end_f
            cursor_s = end_s

        total = offset_f
        # anchor each music piece to the spine item playing when it starts
        vol = plan.get("music_volume_db", 0)
        items = [e for e in elems if "tag" in e]
        for n, pc in enumerate(pieces):
            pos_f = frames(pc["pos"])
            if pos_f >= total:
                break
            host = next(e for e in items if e["offset"] <= pos_f < e["offset"] + e["dur"])
            src0_f = frames(pc["src0"])
            dur_f = min(frames(pc["src1"]) - src0_f, total - pos_f)
            # a short fade at every music splice hides the seam
            fi = frames(pc["fade_in"]) if pc["fade_in"] else (frames(0.05) if n else 0)
            fo = frames(pc["fade_out"]) if pc["fade_out"] else (frames(0.05) if n < len(pieces) - 1 else 0)
            kf = []
            if fi:
                kf += [(src0_f, -60), (src0_f + fi, vol)]
            if fo:
                kf += [(src0_f + dur_f - fo, vol), (src0_f + dur_f, -96)]
            if kf:
                vol_xml = ('<adjust-volume><param name="amount"><keyframeAnimation>'
                           + "".join(f'<keyframe time="{T(t)}" value="{v}dB"/>' for t, v in kf)
                           + '</keyframeAnimation></param></adjust-volume>')
            else:
                vol_xml = f'<adjust-volume amount="{vol}dB"/>'
            anchor = host["local"] + (pos_f - host["offset"])
            clip = (f'<asset-clip {a(ref="m1", lane=-1, offset=T(anchor), name=f"music {n + 1}", start=T(src0_f), duration=T(dur_f), audioRole="music")}>'
                    f'{vol_xml}</asset-clip>')
            # anchored clips go after intrinsic params (volume / transform) and before markers
            idx = next((k for k, x in enumerate(host["inner"]) if x.startswith("<marker")), len(host["inner"]))
            host["inner"].insert(idx, clip)

        spine = []
        for e in elems:
            if "transition" in e:
                spine.append(e["transition"])
            elif e["tag"] == "gap" and not e["inner"]:
                spine.append(f'<gap {e["attrs"]}/>')
            else:
                spine.append(f'<{e["tag"]} {e["attrs"]}>' + "".join(e["inner"]) + f'</{e["tag"]}>')
        name = plan.get("project", "AI cut")
        return (f'<project {a(name=name)}><sequence {a(format="r1", duration=T(total), tcStart="0s", tcFormat="NDF", audioLayout="stereo", audioRate="48k")}>'
                f'<spine>{"".join(spine)}</spine></sequence></project>')

    # ---------- sound effects ----------
    def sfx_resources(self, plans: list[dict]) -> None:
        """plan["sfx"] = {"card": {"file": ".../Cards.caf", "hits": [1.02, 3.78], "dur": 0.3, "db": -4}}
        A segment with "sfx": "card" gets the next hit (rotating) on its own lane at its first frame."""
        self.sfx_ids, self._sfx_turn = {}, {}
        for plan in plans:
            for key, sp in plan.get("sfx", {}).items():
                path = str(Path(sp["file"]).expanduser())
                if path in self.sfx_ids:
                    continue
                out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=sample_rate,channels",
                                      "-of", "json", path], check=True, capture_output=True, text=True).stdout
                info = json.loads(out)
                st = info["streams"][0]
                rid = f"s{len(self.sfx_ids) + 1}"
                self.sfx_ids[path] = rid
                self.res.append(
                    f'<asset {a(id=rid, name=Path(path).stem, start="0s", duration=T(frames(float(info["format"]["duration"]))), hasAudio=1, audioSources=1, audioChannels=st["channels"], audioRate=st["sample_rate"])}>'
                    f'<media-rep kind="original-media" src={quoteattr(url(path))}/></asset>')

    def _sfx(self, plan: dict, seg: dict, local_start_f: int) -> str:
        key = seg["sfx"]
        sp = plan["sfx"][key]
        hits = sp.get("hits") or [0.0]
        n = self._sfx_turn.get(key, 0)
        self._sfx_turn[key] = n + 1
        hit = hits[n % len(hits)]
        rid = self.sfx_ids[str(Path(sp["file"]).expanduser())]
        db = seg.get("sfx_db", sp.get("db", 0))
        return (f'<asset-clip {a(ref=rid, lane=-2, offset=T(local_start_f), name=f"sfx {key}", start=T(frames(max(0.0, hit - 0.01))), duration=T(frames(sp.get("dur", 0.3))), audioRole="effects")}>'
                f'<adjust-volume amount="{db}dB"/></asset-clip>')

    @staticmethod
    def _zoom(zoom, local_start_f: int, dur_f: int, pos=None) -> str:
        z0, z1 = zoom
        p0, p1 = (pos or [[0, 0], [0, 0]])
        return ('<adjust-transform>'
                f'<param name="position"><keyframeAnimation>'
                f'<keyframe time="{T(local_start_f)}" value="{p0[0]} {p0[1]}"/>'
                f'<keyframe time="{T(local_start_f + dur_f)}" value="{p1[0]} {p1[1]}"/>'
                f'</keyframeAnimation></param>'
                f'<param name="scale"><keyframeAnimation>'
                f'<keyframe time="{T(local_start_f)}" value="{z0} {z0}"/>'
                f'<keyframe time="{T(local_start_f + dur_f)}" value="{z1} {z1}"/>'
                f'</keyframeAnimation></param>'
                '</adjust-transform>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plans", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--event", default=None)
    args = ap.parse_args()
    cfg = load_project()
    plans = [json.loads((ROOT / p).read_text()) for p in args.plans]
    photos = {s["photo"] for p in plans for s in p["segments"] if "photo" in s}
    b = Builder(cfg)
    b.resources(photos)
    b.sfx_resources(plans)
    projects = [b.project(p) for p in plans]
    event = args.event or cfg["fcp_event"]
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.13">'
           f'<resources>{"".join(b.res)}</resources>'
           f'<event {a(name=event)}>{"".join(b.event_clips())}{"".join(projects)}</event></fcpxml>\n')
    out = out_path(cfg, args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml)
    if not DTD.exists():                     # Apple's DTD is not redistributed: copy it from the local Final Cut Pro
        app = Path("/Applications/Final Cut Pro.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources") / DTD.name
        if app.exists():
            DTD.parent.mkdir(exist_ok=True)
            DTD.write_bytes(app.read_bytes())
    if DTD.exists():
        r = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(DTD), str(out)], capture_output=True, text=True)
        print("DTD valid" if r.returncode == 0 else "DTD ERRORS:\n" + r.stderr[:3000])
    print(out)


if __name__ == "__main__":
    main()
