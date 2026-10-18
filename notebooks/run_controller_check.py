"""Run notebook 02 (the controller check: train, calibrate, test once, save results) as a script.
Used by the console's "Recompute on IBM LinuxONE" button and handy for the command line."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
nb = ROOT / "notebooks" / "02_controller_check.ipynb"
r = subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                    "--ExecutePreprocessor.timeout=3600", str(nb)], cwd=ROOT / "notebooks", capture_output=True, text=True)
if r.returncode:
    print(r.stderr[-2000:]); sys.exit(1)
res = json.loads((ROOT / "data" / "processed" / "controller_check_results.json").read_text())
print("controller check:", res["summary"]["water_caught"], "of", res["summary"]["water_attacks"], "caught |", res["summary"]["per_day"], "false alarms/day")
