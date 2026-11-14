"""Explain what changed between two FCPXML timelines (e.g. a generated cut vs your hand-edited export).

Compares, on the timeline (absolute seconds):
  * primary-storyline clips: added / removed / moved / trimmed (in-point, duration)
  * connected items by lane: audio (music, sfx), overlays (stamps), titles, adjustment clips
  * audio levels (static and keyframed) of each clip
  * effects (filters), transitions, retiming, transforms
Usage: uv run scripts/diff_fcpxml.py base.fcpxml edited.fcpxmld [--json]
"""
from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET


def tf(s):
    if not s:
        return 0.0
    s = s.rstrip("s")
    return float(Fraction(s)) if s else 0.0


def load(path: str):
    p = Path(path)
    if p.is_dir():
        p = p / "Info.fcpxml"
    root = ET.parse(p).getroot()
    res = {r.get("id"): r for r in root.find("resources")}
    proj = next(root.iter("project"))
    seq = proj.find("sequence")
    return root, res, proj, seq


def vol(el):
    av = el.find("adjust-volume")
    if av is None:
        return None
    if av.get("amount"):
        return av.get("amount")
    s0 = tf(el.get("start"))
    return [(round(tf(k.get("time")) - s0, 2), k.get("value")) for k in av.iter("keyframe")]


def describe(root, res, seq):
    name = lambda e: e.get("name") or (res[e.get("ref")].get("name") if e.get("ref") in res else e.tag)  # noqa: E731
    spine, conn, fx = [], [], []
    for e in seq.find("spine"):
        if e.tag == "transition":
            fx.append({"kind": "transition", "name": e.get("name"), "at": round(tf(e.get("offset")), 2), "dur": round(tf(e.get("duration")), 2)})
            continue
        off, st, du = tf(e.get("offset")), tf(e.get("start")), tf(e.get("duration"))
        item = {"tag": e.tag, "name": name(e), "at": round(off, 2), "in": round(st, 2), "dur": round(du, 2), "vol": vol(e),
                "filters": [f.get("name") for f in e.findall("filter-video")] + [f.get("name") for f in e.findall("filter-audio")],
                "retime": e.find("timeMap") is not None, "transform": e.find("adjust-transform") is not None}
        spine.append(item)
        for ch in e:
            if ch.get("lane") is None:
                continue
            c_at = off + tf(ch.get("offset")) - st
            conn.append({"lane": int(ch.get("lane")), "tag": ch.tag, "name": name(ch), "at": round(c_at, 2),
                         "dur": round(tf(ch.get("duration")), 2), "vol": vol(ch),
                         "filters": [f.get("name") for f in ch.findall("filter-video")] + [f.get("name") for f in ch.findall("filter-audio")],
                         "text": " ".join(t.text or "" for t in ch.iter("text-style")).strip() or None})
    return spine, conn, fx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("edited")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    A, B = load(args.base), load(args.edited)
    sa, ca, fa = describe(A[0], A[1], A[3])
    sb, cb, fb = describe(B[0], B[1], B[3])
    out = {"length": [round(tf(A[3].get("duration")), 2), round(tf(B[3].get("duration")), 2)],
           "project": [A[2].get("name"), B[2].get("name")], "spine": [], "connected": [], "fx": []}

    # primary storyline: match clips by (name, source in-point) so moves and trims are recognised
    key = lambda c: (c["name"], round(c["in"], 1))  # noqa: E731
    used = set()
    for c in sb:
        m = next((i for i, a in enumerate(sa) if i not in used and key(a) == key(c)), None)
        if m is None:
            m = next((i for i, a in enumerate(sa) if i not in used and a["name"] == c["name"] and abs(a["in"] - c["in"]) < 2.0), None)
        if m is None:
            out["spine"].append({"change": "added", **c})
            continue
        used.add(m)
        a = sa[m]
        diffs = {k: [a[k], c[k]] for k in ("at", "in", "dur", "vol", "filters", "retime", "transform") if a[k] != c[k]}
        if diffs:
            out["spine"].append({"change": "changed", "name": c["name"], "at": c["at"], **diffs})
    for i, a in enumerate(sa):
        if i not in used:
            out["spine"].append({"change": "removed", **a})

    ck = lambda c: (c["lane"], c["name"], c["tag"])  # noqa: E731
    used = set()
    for c in cb:
        m = next((i for i, a in enumerate(ca) if i not in used and ck(a) == ck(c) and abs(a["at"] - c["at"]) < 1.0), None)
        if m is None:
            m = next((i for i, a in enumerate(ca) if i not in used and a["name"] == c["name"] and abs(a["at"] - c["at"]) < 3.0), None)
        if m is None:
            out["connected"].append({"change": "added", **c})
            continue
        used.add(m)
        a = ca[m]
        diffs = {k: [a[k], c[k]] for k in ("lane", "at", "dur", "vol", "filters", "text") if a[k] != c[k]}
        if diffs:
            out["connected"].append({"change": "changed", "name": c["name"], **diffs})
    for i, a in enumerate(ca):
        if i not in used:
            out["connected"].append({"change": "removed", **a})
    if fa != fb:
        out["fx"] = {"base": fa, "edited": fb}

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    print(f"project: {out['project'][0]}  ->  {out['project'][1]}")
    print(f"length:  {out['length'][0]}s  ->  {out['length'][1]}s")
    print(f"\nPRIMARY STORYLINE ({len(sa)} -> {len(sb)} items)")
    for d in out["spine"]:
        print("  ", d["change"].upper(), {k: v for k, v in d.items() if k != "change"})
    print("\nCONNECTED (lane >0 video/titles above, <0 audio below)")
    for d in out["connected"]:
        print("  ", d["change"].upper(), {k: v for k, v in d.items() if k != "change"})
    if out["fx"]:
        print("\nTRANSITIONS", out["fx"])


if __name__ == "__main__":
    main()
