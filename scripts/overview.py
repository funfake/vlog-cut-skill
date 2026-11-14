"""One overview image: middle frame of every clip, labelled with name, length and local time."""
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parent))
from common import load_project
cfg = load_project(); w = cfg["work"]
clips = sorted((w / "clips").glob("*.json"))
cols, tw, th = 7, 300, 169
rows = (len(clips) + cols - 1) // cols
sheet = Image.new("RGB", (cols * tw, rows * (th + 18)), (15, 15, 15)); d = ImageDraw.Draw(sheet)
for i, p in enumerate(clips):
    j = json.loads(p.read_text()); info = j["info"]; keys = j["keyframes"]
    t = keys[len(keys) // 2]
    img = Image.open(w / "frames" / info["name"] / f"{info['name']}_{t:06.2f}.jpg").resize((tw, th))
    x, y = (i % cols) * tw, (i // cols) * (th + 18); sheet.paste(img, (x, y))
    # Sony writes local wall-clock time tagged as Z
    lt = info["creation_time"][11:16] if info.get("creation_time") else "?"
    s = j["summary"]
    d.text((x + 3, y + th + 2), f"{info['name']} {info['duration']:.0f}s {lt} mot{s['motion']:.0f} shk{s['shake']:.1f}", fill=(230, 230, 230))
sheet.save(w / "overview.jpg", quality=85); print(w / "overview.jpg")
