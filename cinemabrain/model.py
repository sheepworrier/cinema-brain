"""Shape of the records a Source produces (plain dicts, serialised straight to data.json).

Film = {
  "key": str,               # stable id, e.g. "odeon:HO00008986"
  "title": str, "cert": str, "certNote": str|None, "runtime": int|None,
  "release": "YYYY-MM-DD"|None, "synopsis": str, "actors": [str], "genres": [str],
  "isEvent": bool, "comingSoon": bool,
  "links": {cinema_id: url},
  "shows": [Showtime],
  "bookingFrom": {cinema_id: "YYYY-MM-DD"},   # first screening date per cinema (any distance ahead)
}
Showtime = {"c": cinema_id, "d": "YYYY-MM-DD", "t": "HH:MM", "tags": [str], "sold": bool}
Cinema = {"id": str, "name": str, "url": str}

Enrichment later adds: "imdb": {"id","rating","votes"}, "tmdb": {"id","url"},
"series": {"name","url"}|None, "rerelease": bool.
"""
