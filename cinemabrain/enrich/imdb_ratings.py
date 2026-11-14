"""IMDb rating + vote count from IMDb's free daily dataset (title.ratings.tsv.gz).

https://developer.imdb.com/non-commercial-datasets/ - personal, non-commercial use.
"""
from __future__ import annotations

import gzip
import time

from ..util import ROOT, http_get

URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
LOCAL = ROOT / "cache" / "title.ratings.tsv.gz"


def _download(max_age_hours: float = 20) -> None:
    if LOCAL.exists() and time.time() - LOCAL.stat().st_mtime < max_age_hours * 3600:
        return
    LOCAL.parent.mkdir(exist_ok=True)
    data = http_get(URL, timeout=120)
    tmp = LOCAL.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(LOCAL)


def enrich(films: list[dict], max_age_hours: float = 20) -> None:
    want: dict[str, list[dict]] = {}
    for f in films:  # the same film can appear once per cinema, so keep every copy
        if f.get("imdb", {}).get("id"):
            want.setdefault(f["imdb"]["id"], []).append(f)
    if not want:
        return
    try:
        _download(max_age_hours)
    except Exception as e:
        print(f"  ! IMDb ratings download failed ({e}); using previous copy if any")
        if not LOCAL.exists():
            return
    with gzip.open(LOCAL, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            tt, _, rest = line.partition("\t")
            if tt in want:
                rating, votes = rest.rstrip("\n").split("\t")
                for f in want[tt]:
                    f["imdb"].update(rating=float(rating), votes=int(votes))
