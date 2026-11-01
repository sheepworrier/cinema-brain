# CinemaBrain

A weekly page of what's showing at ODEON Brighton, plus films coming in the next month. Each film has
its IMDb rating, cast, certificate and series info. You can sort and filter, and every view can be shared
by link (the state lives in the URL).

- `cinemabrain/sources/odeon.py`: opens real Chrome (needed to get past Cloudflare), grabs the
  ODEON API token, then pulls showtimes, films and certificates. To add cinemas later, write another
  Source and add it to `sources()` in `cinemabrain/build.py`.
- `cinemabrain/enrich/tmdb.py`: cast, IMDb id and "Part of a series" (TMDB collection).
  Wrong matches can be fixed in `overrides.json`: `{"ODEON title": <tmdb id or null>}`.
- `cinemabrain/enrich/imdb_ratings.py`: rating and votes from IMDb's free daily dataset.
- `docs/`: the static site served by GitHub Pages (`index.html` and `data.json`).
- `run_weekly.sh` + `launchd/com.cinemabrain.weekly.plist`: build, push and notify every Thursday at 07:00.

```sh
.venv/bin/python -m cinemabrain.build              # full build (a Chrome window opens briefly)
.venv/bin/python -m cinemabrain.build --reuse-raw  # re-enrich without re-scraping
(cd docs && python3 -m http.server 8765)           # preview at http://localhost:8765
tail -50 ~/Library/Logs/cinemabrain.log            # weekly job log
```

URL parameters: `tab=now|soon`, `days=sat,sun`, `after=17:00`, `before=21:00`, `cert=U|PG|12A|15`
(max), `series=yes|no`, `min=7`, `q=text`, `sort=imdb|votes|title|time|cert|runtime|release`, `dir=asc|desc`.
