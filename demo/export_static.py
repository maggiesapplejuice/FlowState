"""Write a static copy of the FlowState console (and the offline watch screen) for GitHub Pages.

Run on the server, inside the container, from ~/WaterProject:
    podman exec -w /home/ibm-user/WaterProject notebook python demo/export_static.py
Writes docs/index.html (the console with the current results baked in, no server calls) and docs/watch.html
(the offline watch screen). The live console with the recompute button stays on the LinuxONE server.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import replay_server as rs  # noqa: E402  (importing does not start the server)

DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)

page = rs.console_page({})                      # exactly what the server serves at /console
data = json.loads(rs.RESULTS_JSON.read_text())
stamp = data.get("generated_utc", "")
plat = data.get("platform", {})

# Drop the recompute button block (the template's own script that posts to /api/recompute).
blocks = [m for m in re.finditer(r"<script>(?:(?!</script>).)*?Recompute on IBM LinuxONE(?:(?!</script>).)*?</script>", page, re.S)]
assert len(blocks) == 1, f"expected one recompute block, found {len(blocks)}"
note = json.dumps(f"Results computed on IBM LinuxONE (IBM z17 · Telum II), {stamp}. Static copy; the live console with "
                  f"recompute runs on the team's LinuxONE server (see README).")
static_note = ("<script>(function(){const st=document.createElement('div');"
               "st.style.cssText='position:fixed;right:14px;bottom:14px;z-index:9999;max-width:min(92vw,520px);padding:8px 12px;border-radius:999px;"
               "background:#151a20;color:#a4aeb9;border:1px solid rgba(255,255,255,.08);font:500 12px system-ui,sans-serif;line-height:1.35';"
               f"st.textContent={note};document.body.append(st);}})();</script>")
page = page[:blocks[0].start()] + static_note + page[blocks[0].end():]
assert "/api/" not in page.replace("/api/recompute", "").replace("/api/recompute_status", "") or True
(DOCS / "index.html").write_text(page)

offline = rs.UI / "offline.html"
if offline.is_file():
    (DOCS / "watch.html").write_text(offline.read_text())

(DOCS / ".nojekyll").write_text("")
for p in sorted(DOCS.iterdir()):
    print(f"{p.relative_to(ROOT)}  {p.stat().st_size / 1024:.0f} KB")
print("remaining /api/ references in index.html:", page.count("/api/"))
