"""Build the demo site in docs/ (for GitHub Pages).

    python3 tools/build_demo.py

What it does:
  1. Copies the engine (*.py) and data/*.json into docs/engine/, so the browser can run the
     same code you run in the terminal. The files in the repo root stay the single source of
     truth: edit those, then run this script again.
  2. Writes docs/engine/manifest.json, the list of files the page loads into Pyodide.
  3. Runs the engine for each preset and saves the results to docs/presets.json. The page
     shows these instantly, and falls back to them if the live engine can't load.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ENGINE = DOCS / "engine"

PY_FILES = [
    "models.py", "loader.py", "solver.py", "agent.py", "bus.py", "course_finder.py",
    "negotiation.py", "swaps.py", "confirm.py", "phrasing.py", "webapi.py",
]

PRESETS = [
    {"id": "base", "name": "The base story",
     "blurb": "Ben gives up a preference, and Ana swaps into a full class.",
     "options": {}},
    {"id": "ben-no", "name": "Ben says no first",
     "blurb": "Ben turns down the first plan, so the agents start over.",
     "options": {"say_no_first": ["ben"]}},
    {"id": "no-swap", "name": "Nobody will swap",
     "blurb": "Priya keeps the PHIL215-04 seat, so the full class is out.",
     "options": {"priya_willing": False}},
    {"id": "flexible", "name": "Everyone is flexible",
     "blurb": "No one has a soft preference, so nothing needs relaxing.",
     "options": {"ben_friday_priority": 0, "maya_max_days": None, "ana_no_early": False}},
    {"id": "stuck", "name": "Two friends say no",
     "blurb": "The agents run out of options and hand the decision back to the students.",
     "options": {"say_no_first": ["ana", "ben"]}},
]


def main() -> None:
    sys.path.insert(0, str(ROOT))
    if ENGINE.exists():
        shutil.rmtree(ENGINE)
    (ENGINE / "data").mkdir(parents=True)

    manifest = []
    for name in PY_FILES:
        shutil.copy(ROOT / name, ENGINE / name)
        manifest.append(name)
    for path in sorted((ROOT / "data").glob("*.json")):
        shutil.copy(path, ENGINE / "data" / path.name)
        manifest.append(f"data/{path.name}")
    (ENGINE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    import webapi  # imported after sys.path is set; runs the same engine as run_demo.py

    out = []
    for p in PRESETS:
        run = json.loads(webapi.run(json.dumps(p["options"])))
        out.append({**p, "run": run})
        r = run["result"]
        print(f"{p['id']:<9} {r['status']:<10} {r['section_id']}  level {r['level']}  "
              f"{run['audit']['messages']} messages, {run['audit']['leaks']} leaks")
    (DOCS / "presets.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {DOCS / 'presets.json'} and {len(manifest)} engine files.")


if __name__ == "__main__":
    main()
