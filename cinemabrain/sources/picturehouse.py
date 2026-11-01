"""Picturehouse cinemas (Duke of York's, Duke's at Komedia) via picturehouses.com's own AJAX endpoint.

The endpoint wants the session's XSRF cookie echoed back as a header (Laravel style). It returns the
whole group's films for one date, so we fetch each date once and share it between cinemas.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from ..util import UA, norm_cert, slugify

BASE = "https://www.picturehouses.com"
HIDE_TAGS = {"2d", "ad-trailer", "ad trailer", "no trailers", "adtrailer", "laser", "audio d", "sub cinema"}

_cache: dict = {}  # shared between the two Picturehouse cinemas within one run


class _Session:
    def __init__(self, page_path: str):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.referer = BASE + page_path
        req = urllib.request.Request(self.referer, headers={"User-Agent": UA})
        self.op.open(req, timeout=30).read()
        self.token = next((urllib.parse.unquote(c.value) for c in self.jar if c.name == "XSRF-TOKEN"), "")

    def movies(self, d: str, cinema_code: str) -> dict:
        key = d
        if key in _cache:
            return _cache[key]
        body = urllib.parse.urlencode({"start_date": d, "cinema_id": cinema_code, "filters": ""}).encode()
        req = urllib.request.Request(
            BASE + "/api/get-movies-ajax",
            data=body,
            headers={
                "User-Agent": UA,
                "X-XSRF-TOKEN": self.token,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": self.referer,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        data = json.loads(self.op.open(req, timeout=60).read())
        if data.get("response") != "success":
            raise RuntimeError(f"Picturehouse API said {data.get('response')!r} for {d}")
        _cache[key] = data
        return data


class PicturehouseSource:
    def __init__(self, cinema_id: str, code: str, slug: str, name: str):
        self.code = code
        self.slug = slug
        self.cinema = {"id": cinema_id, "name": name, "url": f"{BASE}/cinema/{slug}"}

    def fetch(self, start: date, days: int = 7, soon_days: int = 31) -> list[dict]:
        cid, code = self.cinema["id"], self.code
        sess = _Session(f"/cinema/{self.slug}")
        films: dict[str, dict] = {}
        meta: dict[str, dict] = {}

        def parse_date(s: str | None) -> str | None:
            try:
                return datetime.strptime(s, "%d %b %Y").date().isoformat()
            except Exception:
                return None

        def rec_for(m: dict) -> dict:
            fid = m["ScheduledFilmId"]
            if fid not in films:
                title = re.sub(r"\s+", " ", m["Title"]).strip()
                rt = int(m["RunTime"]) if str(m.get("RunTime") or "").isdigit() else None
                films[fid] = {
                    "key": f"{cid}:{fid}",
                    "title": title,
                    "cert": norm_cert(m.get("Rating")),
                    "certNote": None,
                    "runtime": rt or None,
                    "release": parse_date(m.get("OpeningDate")),
                    "synopsis": "",
                    "actors": [],
                    "genres": [],
                    "isEvent": False,
                    "comingSoon": False,
                    "links": {cid: f"{BASE}/movie-details/{code}/{fid}/{slugify(title)}"},
                    "shows": [],
                    "bookingFrom": {},
                }
            return films[fid]

        soon_end = (start + timedelta(days=soon_days)).isoformat()
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            data = sess.movies(d, code)
            for m in data["movies"]:
                meta.setdefault(m["ScheduledFilmId"], m)
                for st in m.get("show_times") or []:
                    if st.get("CinemaId") != code:
                        continue
                    f = rec_for(meta[st["ScheduledFilmId"]] if st["ScheduledFilmId"] in meta else m)
                    tags = [t.strip() for t in st.get("SessionAttributesNames") or [] if t.strip().lower() not in HIDE_TAGS]
                    f["shows"].append(
                        {"c": cid, "d": st["date_f"], "t": st["time"], "tags": tags, "sold": st.get("SeatsAvailable") == 0}
                    )
                    f["bookingFrom"].setdefault(cid, st["date_f"])

        # Coming soon: films this cinema will get, opening within the next month
        for fid, m in meta.items():
            if code not in (m.get("available_cinemas") or []):
                continue
            rel = parse_date(m.get("OpeningDate"))
            if rel and start.isoformat() < rel <= soon_end:
                rec_for(m)["comingSoon"] = True
        for f in films.values():
            f["shows"].sort(key=lambda s: (s["d"], s["t"]))
            f["shows"] = [dict(t) for t in {(s["d"], s["t"], tuple(s["tags"]), s["sold"]): s for s in f["shows"]}.values()]
            f["shows"].sort(key=lambda s: (s["d"], s["t"]))
        return list(films.values())
