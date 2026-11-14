"""Daily light job: refresh IMDb ratings in docs/data.json (no browser, no cinema fetching).

New releases only gain a rating a day or more after opening, so the weekly build can miss them.
Exits 0 and leaves the file alone when nothing changed.
"""
from __future__ import annotations

import json

from .enrich import imdb_ratings
from .util import ROOT


def main():
    path = ROOT / "docs" / "data.json"
    data = json.loads(path.read_text())
    before = {f["key"]: f.get("imdb") for f in data["films"]}
    imdb_ratings.enrich(data["films"], max_age_hours=1)  # always get the latest daily file
    changed = [f["title"] for f in data["films"] if f.get("imdb") != before[f["key"]]]
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"Ratings refreshed: {len(changed)} film(s) changed" + (": " + "; ".join(changed) if changed else ""))


if __name__ == "__main__":
    main()
