"""Bake every demo episode into a self-contained copy of the watch UI (demo/ui/offline.html) that needs no
server. Scores, alarm seconds and a pre-generated incident brief are computed here on IBM LinuxONE.
Run inside the container, from ~/WaterProject:  python demo/bake.py
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import replay_server as rs

rs.REPLAY = rs.Replay()
R = rs.REPLAY
BRIEFS = rs.UI / "briefs.json"           # briefs already written by an earlier bake are reused
cached = json.loads(BRIEFS.read_text()) if BRIEFS.exists() else {}
episodes = {}
for ep in [e["id"] for e in R.episode_list()]:
    meta = R.load_episode(ep)
    with R.lock:
        R.i = meta["n"] - 1                 # advance to the end so the state holds the whole episode
    st = R.state(since=-1)
    full = dict(st["series"]); full["clock"] = [str(t) for t in R.df.timestamp]; full["attack"] = R.df.attack.astype(int).tolist(); full["demand"] = R.df.P4_HT_PS.round(2).tolist()
    brief = None
    first = next((i for i, a in enumerate(R.alarm) if a), None)
    if first is not None and ep in cached:
        brief = dict(cached[ep]); brief["pregenerated"] = True
        rs.log(f"{ep}: first alarm at {first} s, brief reused from an earlier bake")
    elif first is not None:
        with R.lock:
            R.i = first; R.brief_status = "none"; R.brief = None
            R.start_brief()
        t0 = time.time()
        while R.brief_status != "done" and time.time() - t0 < 300:
            time.sleep(1)
        brief = dict(R.brief); brief["pregenerated"] = True
        rs.log(f"{ep}: first alarm at {first} s, brief written in {brief.get('written_in_s')} s")
        cached[ep] = brief; BRIEFS.write_text(json.dumps(cached, indent=1))
    episodes[ep] = {"meta": meta, "full": full, "brief": brief}
baked = {"default": "A214", "platform": R.platform, "list": R.episode_list(), "episodes": episodes}
ui = (rs.UI / "index.html").read_text()
payload = json.dumps(baked, default=str, separators=(",", ":")).replace("</", "<\\/")
out = ui.replace("<script>\n(function () {", f"<script>window.BAKED = {payload};</script>\n<script>\n(function () {{", 1)
(rs.UI / "offline.html").write_text(out)
rs.log(f"wrote demo/ui/offline.html ({len(out) / 1024:.0f} KB)")
