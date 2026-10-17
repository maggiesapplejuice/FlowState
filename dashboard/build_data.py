"""Collect everything the dashboard shows into dashboard/data.json. Run on the server after notebook 02 and 03:

    podman exec -w /home/ibm-user/WaterProject notebook python dashboard/build_data.py
"""
import json, math, platform, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_loading import PROCESSED, NAMES, ATTACK_TYPES

res = json.loads((PROCESSED / "controller_check_results.json").read_text())
traces = json.loads((PROCESSED / "controller_check_traces.json").read_text())
cpu = open("/proc/cpuinfo").read()
try:
    import torch, torch_nnpa  # noqa
    telum2 = bool(torch.nnpa.is_telum2_available())
except Exception:
    telum2 = None
plat = {"arch": platform.machine(),
        "machine_type": cpu.split("machine = ")[1].split()[0] if "machine = " in cpu else None,
        "nnpa": "nnpa" in cpu.split("features")[1].split("\n")[0], "telum2": telum2,
        "os": [l.split("=")[1].strip().strip('"') for l in open("/etc/os-release") if l.startswith("PRETTY_NAME")][0]}
brief = None
try:
    nb = json.loads((ROOT / "notebooks" / "03_incident_brief.ipynb").read_text())
    brief = "\n".join("".join(o.get("text", "")) for c in nb["cells"] for o in c.get("outputs", []) if o.get("name") == "stdout").strip()
except Exception:
    pass
data = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "platform": plat,
        "results": res, "traces": traces, "brief": brief, "readings": NAMES, "attack_types": ATTACK_TYPES}
def clean(o):
    """Replace NaN and infinity (not valid JSON) with null."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


data = clean(data)
out = ROOT / "dashboard" / "data.json"
out.write_text(json.dumps(data, default=str, allow_nan=False))
print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
