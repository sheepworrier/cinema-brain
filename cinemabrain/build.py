"""Weekly build: fetch listings from every source, enrich, write docs/data.json.

  python -m cinemabrain.build              # full run (opens Chrome briefly)
  python -m cinemabrain.build --reuse-raw  # skip Chrome, reuse cache/raw_*.json (for dev)
  python -m cinemabrain.build --dry-run    # don't write docs/data.json, just print a summary
"""
from __future__ import annotations

import argparse
import collections
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .enrich import imdb_ratings
from .enrich.tmdb import Tmdb, mark_rereleases, update_overrides
from .sources.cineworld import CineworldSource
from .sources.depot import DepotSource
from .sources.odeon import OdeonSource
from .sources.picturehouse import PicturehouseSource
from .util import ROOT, load_env

DAYS = 7
SOON_DAYS = 31
LONDON = ZoneInfo("Europe/London")


def sources():
    # Order matters: the first cinema's title/details win when the same film is merged.
    return [
        OdeonSource("824", "brighton", "ODEON Brighton"),
        PicturehouseSource("duke-of-yorks", "008", "duke-of-york-s-picturehouse", "Duke of York's"),
        PicturehouseSource("komedia", "019", "duke-s-at-komedia", "Duke's at Komedia"),
        CineworldSource(),
        DepotSource(),
    ]


def merge(all_films: list[dict]) -> list[dict]:
    """Merge the same film from different cinemas (keyed on IMDb id, else normalised title)."""
    from .util import norm_title

    out: dict[str, dict] = {}
    for f in all_films:
        k = (f.get("imdb") or {}).get("id") or norm_title(f["title"])
        if k not in out:
            out[k] = f
            continue
        m = out[k]
        m["links"].update(f["links"])
        m["bookingFrom"].update(f["bookingFrom"])
        m["soonAt"] = sorted(set(m.get("soonAt", [])) | set(f.get("soonAt", [])))
        for k in ("runtime", "release", "certNote"):
            m[k] = m.get(k) or f.get(k)
        if m.get("cert") == "TBC" and f.get("cert") != "TBC":
            m["cert"] = f["cert"]
        if len(f.get("synopsis") or "") > len(m.get("synopsis") or ""):
            m["synopsis"] = f["synopsis"]
        m["actors"] = m.get("actors") or f.get("actors") or []
        m["genres"] = m.get("genres") or f.get("genres") or []
        m["rerelease"] = m.get("rerelease") or f.get("rerelease")
        m["isEvent"] = m.get("isEvent") or f.get("isEvent")
        m["shows"] = sorted(m["shows"] + f["shows"], key=lambda s: (s["d"], s["t"]))
        m["comingSoon"] = bool(m["soonAt"])
    return list(out.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reuse-raw", action="store_true")
    args = ap.parse_args()
    load_env()

    now = datetime.now(LONDON)
    start = now.date()
    cinemas, films, errors = [], [], {}
    for src in sources():
        cin = src.cinema
        raw = ROOT / "cache" / f"raw_{cin['id']}.json"
        try:
            if args.reuse_raw and raw.exists():
                got = json.loads(raw.read_text())
            else:
                print(f"Fetching {cin['name']} ...")
                got = src.fetch(start, DAYS, SOON_DAYS)
                raw.parent.mkdir(exist_ok=True)
                raw.write_text(json.dumps(got, indent=1))
        except Exception as e:  # one cinema failing must not lose the others
            errors[cin["id"]] = f"{type(e).__name__}: {e}"[:300]
            print(f"  ! {cin['name']} FAILED: {errors[cin['id']]}")
            continue
        for f in got:
            f["soonAt"] = [cin["id"]] if f.get("comingSoon") else []
        print(f"  {cin['name']}: {len(got)} films, {sum(len(f['shows']) for f in got)} showtimes")
        cinemas.append(cin)
        films.extend(got)
    if not films:
        raise SystemExit("No cinema returned any data - not overwriting docs/data.json")

    print("Enriching via TMDB ...")
    tm = Tmdb()
    tm.enrich(films)
    update_overrides(tm, films)
    mark_rereleases(films)
    print("IMDb ratings ...")
    imdb_ratings.enrich(films)
    films = merge(films)
    for f in films:
        f["nowShowing"] = bool(f["shows"])
    films = [f for f in films if f["nowShowing"] or f["comingSoon"]]
    films.sort(key=lambda f: f["title"].lower())

    dates = [(start + timedelta(days=i)).isoformat() for i in range(DAYS)]
    data = {
        "generated": now.isoformat(timespec="minutes"),
        "dates": dates,
        "soonUntil": (start + timedelta(days=SOON_DAYS)).isoformat(),
        "cinemas": cinemas,
        "errors": errors,
        "films": films,
    }

    per_day = collections.Counter(s["d"] for f in films for s in f["shows"])
    now_n = sum(f["nowShowing"] for f in films)
    soon_n = sum(f["comingSoon"] for f in films)
    print(f"Now showing: {now_n} films · Coming soon: {soon_n}")
    print("Showtimes per day: " + ", ".join(f"{d[5:]}={per_day.get(d, 0)}" for d in dates))
    print(f"TMDB matched: {sum(bool(f.get('tmdb')) for f in films)}/{len(films)} · "
          f"IMDb rated: {sum(bool((f.get('imdb') or {}).get('rating')) for f in films)} · "
          f"Part of a series: {sum(bool(f.get('series')) for f in films)}")
    unmatched = [f["title"] for f in films if not f.get("tmdb")]
    if unmatched:
        print("No TMDB match: " + "; ".join(unmatched))

    if not args.dry_run:
        out = ROOT / "docs" / "data.json"
        out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        print(f"Wrote {out}")
    summary = f"{now_n} films now showing, {soon_n} coming soon, {len(cinemas)} cinemas"
    if errors:
        summary += " - FAILED: " + ", ".join(errors)
    (ROOT / "cache" / "last_summary.txt").write_text(summary)


if __name__ == "__main__":
    main()
