"""Merge dashboard/data.json into dashboard/template.html.
Writes dashboard/index.html (full page, served from the server) and dashboard/artifact.html (for claude.ai)."""
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
payload = json.dumps(json.loads((HERE / "data.json").read_text()), separators=(",", ":")).replace("</", "<\\/")
body = (HERE / "template.html").read_text().replace("/*__DATA__*/", payload)
(HERE / "artifact.html").write_text(body)
head, sep, rest = body.partition("<style>")
page = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        + head + sep + rest.replace("</style>", "</style>\n</head>\n<body>", 1) + "\n</body>\n</html>\n")
(HERE / "index.html").write_text(page)
print(f"wrote index.html ({len(page) / 1024:.0f} KB) and artifact.html")
