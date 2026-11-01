"""TMDB enrichment: IMDb id, main cast, collection ("Part of a series"), synopsis fallback.

Needs TMDB_API_KEY in .env (either the v3 "API Key" or the v4 "API Read Access Token").
Matches are cached in cache/tmdb.json; fix bad matches in overrides.json:
  {"<cinema film title>": 12345}   -> force TMDB movie id
  {"<cinema film title>": null}    -> force "no match"
"""
from __future__ import annotations

import difflib
import json
import os
import re
import urllib.parse
from pathlib import Path

from ..util import ROOT, http_json, norm_title

API = "https://api.themoviedb.org/3"
CACHE = ROOT / "cache" / "tmdb.json"
OVERRIDES = ROOT / "overrides.json"

# Prefixes / suffixes the cinema adds that TMDB won't know about
STRIP_PREFIX = re.compile(
    r"^(odeon (pride nights|kids|silver screen)\s*[-:]\s*|(charity|parent and baby|autism friendly) screening\s*[-:]\s*|iff\s+|disney'?s\s+|disney pixar'?s\s+)",
    re.I,
)
STRIP_SUFFIX = re.compile(
    r"\s*[\(\[][^\)\]]*(anniversary|re-?release|restoration|4k|remaster|extended|sing-?a-?long|subtitled|dubbed|"
    r"imax|3d|preview|early access|fan event|q ?& ?a|live|encore|director'?s cut)[^\)\]]*[\)\]]\s*$",
    re.I,
)
SUFFIX_WORDS = re.compile(r"\s*[-:–]\s*(\d+(st|nd|rd|th) anniversary.*|re-?release|4k restoration)$", re.I)
RERELEASE_HINT = re.compile(r"anniversary|re-?release|restoration|remaster|4k|classic|encore", re.I)
EVENT_HINT = re.compile(
    r"^(met opera|rbo|royal ballet|nt live|national theatre live|andre rieu|bolshoi|cbeebies|"
    r"league of legends|chicken shop date|doctor who:|screen unseen)|\bconcert\b|\bpanto\b|cinema experience|the play\b",
    re.I,
)


def clean_title(t: str) -> str:
    t = STRIP_PREFIX.sub("", t.strip())
    for _ in range(2):
        t = STRIP_SUFFIX.sub("", t)
        t = SUFFIX_WORDS.sub("", t)
    return t.strip(" -:–")


class Tmdb:
    def __init__(self):
        key = os.environ.get("TMDB_API_KEY", "").strip()
        self.enabled = bool(key)
        if key.startswith("eyJ"):
            self._auth = {"Authorization": f"Bearer {key}"}
            self._q = {}
        else:
            self._auth = {}
            self._q = {"api_key": key}
        self.cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
        self.overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}

    def _get(self, path: str, **params) -> dict:
        q = urllib.parse.urlencode({**self._q, **params})
        return http_json(f"{API}{path}?{q}", self._auth)

    def save(self):
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(self.cache, indent=1, sort_keys=True))

    # ---- matching --------------------------------------------------------
    def _search(self, title: str, year: int | None) -> int | None:
        want = norm_title(title)
        tries = [year, year - 1, None] if year else [None]
        best = None
        for y in tries:
            params = {"query": title, "include_adult": "false", "region": "GB"}
            if y:
                params["primary_release_year"] = y
            res = self._get("/search/movie", **params).get("results", [])
            for r in res[:10]:
                cand = [norm_title(r.get("title", "")), norm_title(r.get("original_title", ""))]
                score = max(difflib.SequenceMatcher(None, want, c).ratio() for c in cand)
                ry = int(r["release_date"][:4]) if r.get("release_date") else None
                if y is None and year and ry and ry > year + 1:
                    continue  # a film can't be released after its cinema release
                key = (score, r.get("popularity", 0) if y is None else 0)
                if score >= 0.86 and (best is None or key > best[0]):
                    best = (key, r["id"])
            if best:
                return best[1]
        return None

    def match(self, film: dict) -> int | None:
        title = film["title"]
        if title in self.overrides:
            return self.overrides[title]
        if film.get("isEvent") or EVENT_HINT.search(title):
            return None
        ck = f"{title}|{film.get('release') or ''}"
        if ck in self.cache.get("match", {}):
            return self.cache["match"][ck]
        year = int(film["release"][:4]) if film.get("release") else None
        mid = self._search(clean_title(title), year)
        self.cache.setdefault("match", {})[ck] = mid
        return mid

    def details(self, mid: int) -> dict:
        ck = str(mid)
        # Re-fetch details each run (cast/collections get filled in as release approaches)
        d = self._get(f"/movie/{mid}", append_to_response="credits,external_ids")
        cast = [c["name"] for c in sorted(d.get("credits", {}).get("cast", []), key=lambda c: c.get("order", 99))][:4]
        coll = d.get("belongs_to_collection")
        info = {
            "id": mid,
            "url": f"https://www.themoviedb.org/movie/{mid}",
            "imdb": (d.get("external_ids") or {}).get("imdb_id") or d.get("imdb_id"),
            "cast": cast,
            "overview": d.get("overview") or "",
            "year": int(d["release_date"][:4]) if d.get("release_date") else None,
            "series": {"name": coll["name"], "url": f"https://www.themoviedb.org/collection/{coll['id']}"} if coll else None,
        }
        self.cache.setdefault("details", {})[ck] = info
        return info

    def enrich(self, films: list[dict]) -> None:
        if not self.enabled:
            print("  ! TMDB_API_KEY not set - skipping TMDB/IMDb enrichment")
            return
        for f in films:
            try:
                mid = self.match(f)
                info = self.details(mid) if mid else None
            except Exception as e:  # network hiccup: fall back to last cached details
                print(f"  ! TMDB error for {f['title']}: {e}")
                ck = f"{f['title']}|{f.get('release') or ''}"
                mid = self.cache.get("match", {}).get(ck)
                info = self.cache.get("details", {}).get(str(mid)) if mid else None
            if not info:
                f["tmdb"] = None
                f["series"] = None
                continue
            f["tmdb"] = {"id": info["id"], "url": info["url"]}
            f["series"] = info["series"]
            if info.get("imdb"):
                f["imdb"] = {"id": info["imdb"]}
            if info["cast"]:
                f["actors"] = info["cast"]
            if not f.get("synopsis") and info["overview"]:
                f["synopsis"] = info["overview"]
            rel_year = int(f["release"][:4]) if f.get("release") else None
            if info.get("year") and rel_year and rel_year - info["year"] >= 2:
                f["rerelease"] = True
        self.save()


def mark_rereleases(films: list[dict]) -> None:
    for f in films:
        if RERELEASE_HINT.search(f["title"]):
            f["rerelease"] = True
        f.setdefault("rerelease", False)
