"""ODEON source.

odeon.co.uk sits behind a Cloudflare challenge, so we open the real Google Chrome via
Playwright (headed; headless gets challenged), let the cinema page load, and capture the
short-lived bearer JWT the site uses for the Vista OCAPI (vwc.odeon.co.uk). We then call
OCAPI directly through the same browser context.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..util import slugify

OCAPI = "https://vwc.odeon.co.uk/WSVistaWebClient/ocapi/v1"
PROFILE = Path(os.path.expanduser("~/.cinemabrain/chrome-profile"))
LONDON = ZoneInfo("Europe/London")

# Showtime attributes that are noise for choosing a film (shown on almost every showing).
HIDE_ATTRS = {"AudioDes", "Wheelchair", "Flash", "Laser", "EventCinem", "£1 web"}
RENAME_ATTRS = {"OpenCapt": "Subtitled", "EnglishSub": "Eng subs", "ODEON Kids": "Kids"}


def _attr_label(a: dict) -> str | None:
    short = a["shortName"]["text"]
    if short in HIDE_ATTRS:
        return None
    if short in RENAME_ATTRS:
        return RENAME_ATTRS[short]
    name = a["name"]["text"]
    m = re.match(r"(.+?) \(Audio\)$", name)
    if m:
        return m.group(1) + " audio"
    return name if len(name) <= 16 else short


class OdeonSource:
    def __init__(self, site_id: str = "824", slug: str = "brighton", name: str = "ODEON Brighton"):
        self.site_id = site_id
        self.page_url = f"https://www.odeon.co.uk/cinemas/{slug}/"
        self.cinema = {"id": f"odeon-{slug}", "name": name, "url": self.page_url}

    # ---- browser / token -------------------------------------------------
    def _open(self):
        from playwright.sync_api import sync_playwright

        PROFILE.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE),
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-position=0,2000",  # park the window off-screen-ish
                "--window-size=1100,800",
            ],
        )
        page = self._ctx.new_page()
        token = {}

        def on_request(req):
            if req.url.startswith(OCAPI) and "authorization" in req.headers:
                token["v"] = req.headers["authorization"]

        page.on("request", on_request)
        page.goto(self.page_url, wait_until="domcontentloaded", timeout=90_000)
        deadline = time.time() + 120
        while "v" not in token and time.time() < deadline:
            page.wait_for_timeout(1000)
        if "v" not in token:
            title = page.title()
            self.close()
            raise RuntimeError(
                f"Could not obtain ODEON API token (page title: {title!r}). "
                "Cloudflare may need a manual check: run the job by hand and click the box in Chrome."
            )
        self._token = token["v"]
        self._page = page

    def close(self):
        for attr in ("_ctx", "_pw"):
            obj = getattr(self, attr, None)
            if obj:
                try:
                    obj.close() if attr == "_ctx" else obj.stop()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _get(self, path: str) -> dict:
        r = self._ctx.request.get(
            OCAPI + path,
            headers={"Authorization": self._token, "Accept": "application/json"},
            timeout=60_000,
        )
        if not r.ok:
            raise RuntimeError(f"OCAPI {path} -> HTTP {r.status}")
        return r.json()

    # ---- main ------------------------------------------------------------
    def fetch(self, start: date, days: int = 7, soon_days: int = 31) -> list[dict]:
        self._open()
        try:
            return self._fetch(start, days, soon_days)
        finally:
            self.close()

    def _fetch(self, start: date, days: int, soon_days: int) -> list[dict]:
        sid, cid = self.site_id, self.cinema["id"]
        films_resp = self._get("/films")
        avail = self._get("/films/availability")
        dates_resp = self._get(f"/film-screening-dates?siteIds={sid}")

        cast = {c["id"]: c["name"] for c in films_resp["relatedData"].get("castAndCrew", [])}
        certs = {c["id"]: c["classification"]["text"] for c in films_resp["relatedData"].get("censorRatings", [])}
        genres = {g["id"]: g["name"]["text"] for g in films_resp["relatedData"].get("genres", [])}
        coming = {a["filmId"] for a in avail["filmAvailabilities"] if "ComingSoon" in a["categories"]}

        window = [start + timedelta(days=i) for i in range(days)]
        soon_end = start + timedelta(days=soon_days)

        booking_from: dict[str, str] = {}
        window_dates = set()
        for d in dates_resp["filmScreeningDates"]:
            bd = d["businessDate"]
            for fs in d["filmScreenings"]:
                if any(s["siteId"] == sid for s in fs["sites"]):
                    booking_from.setdefault(fs["filmId"], bd)
                    if start.isoformat() <= bd < (start + timedelta(days=days)).isoformat():
                        window_dates.add(bd)

        films: dict[str, dict] = {}

        def film_record(f: dict) -> dict:
            fid = f["id"]
            if fid in films:
                return films[fid]
            title = re.sub(r"\s+", " ", f["title"]["text"]).strip()
            actors = []
            for m in f.get("castAndCrew", []):
                if "Actor" in m.get("roles", []) and m["castAndCrewMemberId"] in cast:
                    n = cast[m["castAndCrewMemberId"]]
                    actors.append(" ".join(x for x in (n.get("givenName"), n.get("familyName")) if x))
            note = f.get("censorRatingNote")
            rec = {
                "key": f"odeon:{fid}",
                "title": title,
                "cert": certs.get(f.get("censorRatingId"), "TBC"),
                "certNote": note["text"] if note else None,
                "runtime": f.get("runtimeInMinutes") or None,
                "release": (f.get("releaseDate") or "")[:10] or None,
                "synopsis": (f.get("synopsis") or {}).get("text") or (f.get("shortSynopsis") or {}).get("text") or "",
                "actors": actors[:4],
                "genres": [genres[g] for g in f.get("genreIds", []) if g in genres],
                "isEvent": bool(f.get("eventId")),
                "comingSoon": False,
                "links": {cid: f"https://www.odeon.co.uk/films/{slugify(title)}/{fid}/"},
                "shows": [],
                "bookingFrom": {cid: booking_from[fid]} if fid in booking_from else {},
            }
            films[fid] = rec
            return rec

        # Showtimes for each day in the window
        for d in window:
            ds = d.isoformat()
            if ds not in window_dates:
                continue
            resp = self._get(f"/showtimes/by-business-date/{ds}?siteIds={sid}")
            rel = resp["relatedData"]
            attrs = {a["id"]: _attr_label(a) for a in rel.get("attributes", [])}
            for c in rel.get("castAndCrew", []):
                cast.setdefault(c["id"], c["name"])
            for c in rel.get("censorRatings", []):
                certs.setdefault(c["id"], c["classification"]["text"])
            rel_films = {f["id"]: f for f in rel.get("films", [])}
            for s in resp["showtimes"]:
                f = rel_films.get(s["filmId"])
                if not f:
                    continue
                rec = film_record(f)
                starts = datetime.fromisoformat(s["schedule"]["startsAt"]).astimezone(LONDON)
                tags = [attrs[a] for a in s.get("attributeIds", []) if attrs.get(a)]
                if s.get("requires3dGlasses") and "3D" not in tags:
                    tags.append("3D")
                rec["shows"].append(
                    {"c": cid, "d": ds, "t": starts.strftime("%H:%M"), "tags": tags, "sold": bool(s.get("isSoldOut"))}
                )

        # Coming soon: national ODEON coming-soon list, released within the window
        all_films = {f["id"]: f for f in films_resp["films"]}
        for fid in coming:
            f = all_films.get(fid)
            if not f or not f.get("releaseDate"):
                continue
            rel_d = f["releaseDate"][:10]
            if not (start.isoformat() < rel_d <= soon_end.isoformat()):
                continue
            # One-off events (opera, theatre, concerts) only count if this cinema has them booked
            if f.get("eventId") and fid not in booking_from:
                continue
            film_record(f)["comingSoon"] = True
        # Films already in the window whose release date is still ahead also count as coming soon
        for fid, rec in films.items():
            if rec["release"] and start.isoformat() < rec["release"] <= soon_end.isoformat():
                rec["comingSoon"] = True

        for rec in films.values():
            rec["shows"].sort(key=lambda s: (s["d"], s["t"]))
        return list(films.values())
