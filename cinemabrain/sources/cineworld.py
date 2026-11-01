"""Cineworld Brighton (Marina). cineworld.co.uk is behind Cloudflare, so like ODEON we open real Chrome and
call the site's own BoxOfficeAPI (/api/gatsby-source-boxofficeapi/...) from inside the loaded page."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from ..util import clean_tag, norm_cert

PROFILE = Path(os.path.expanduser("~/.cinemabrain/chrome-profile"))
API = "https://www.cineworld.co.uk/api/gatsby-source-boxofficeapi/"
HIDE_TAGS = {"Digital", "Laser", "Audio Description", "4k", "Big Screen Classics", "Alternative Content"}
RENAME_TAGS = {"Subtitled": "Subtitled"}


class CineworldSource:
    def __init__(self, cinema_id="cineworld-brighton", site="014", theater="X079B", slug="brighton", name="Cineworld Brighton Marina"):
        self.theater, self.site = theater, site
        self.page_url = f"https://www.cineworld.co.uk/cinemas/{slug}/{site}"
        self.cinema = {"id": cinema_id, "name": name, "url": self.page_url}

    def fetch(self, start: date, days: int = 7, soon_days: int = 31) -> list[dict]:
        from playwright.sync_api import sync_playwright

        PROFILE.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE), channel="chrome", headless=False,
                args=["--disable-blink-features=AutomationControlled", "--window-position=0,2000", "--window-size=1100,800"],
            )
            try:
                page = ctx.new_page()
                page.goto(self.page_url, wait_until="domcontentloaded", timeout=90_000)

                def get(path: str):
                    for attempt in range(30):  # Cloudflare check may take a few seconds to clear
                        st, body = page.evaluate(
                            "async u=>{try{const r=await fetch(u);return [r.status,await r.text()]}catch(e){return [0,String(e)]}}",
                            API + path,
                        )
                        if st == 200:
                            return json.loads(body)
                        page.wait_for_timeout(2000)
                    raise RuntimeError(f"Cineworld API {path.split('?')[0]} kept returning {st}")

                return self._fetch(get, start, days, soon_days)
            finally:
                ctx.close()

    def _fetch(self, get, start: date, days: int, soon_days: int) -> list[dict]:
        cid = self.cinema["id"]
        win_end = start + timedelta(days=days)
        q = urllib.parse.urlencode({
            "from": f"{start.isoformat()}T00:00:00",
            "to": f"{win_end.isoformat()}T03:00:00",
            "nin": "Showtime.Category.ExhibitorSelection",
            "theaters": json.dumps({"id": self.theater, "timeZone": "Europe/London"}, separators=(",", ":")),
        })
        sched = get("schedule?" + q)[self.theater]["schedule"]
        soon = get("moviesComingSoon")
        soon_end = (start + timedelta(days=soon_days)).isoformat()
        soon_ids = [
            s["movie"]["id"] for s in soon
            if start.isoformat() < s["from"] <= soon_end and (not s.get("theaterIds") or self.theater in s["theaterIds"])
        ]
        ids = list(dict.fromkeys(list(sched.keys()) + soon_ids))
        movies: dict[str, dict] = {}
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            for m in get("movies?basic=false&castingLimit=3&" + "&".join("ids=" + c for c in chunk)):
                movies[str(m["id"])] = m

        out = []
        for mid in ids:
            m = movies.get(mid)
            if not m:
                continue
            title = re.sub(r"\s+", " ", m.get("title") or "").strip()
            rel = ((m.get("releases") or [{}])[0].get("releasedAt") or "")[:10] or None
            rec = {
                "key": f"{cid}:{mid}",
                "title": title,
                "cert": norm_cert(m.get("certificate")),
                "certNote": ((m.get("releases") or [{}])[0].get("rating") or {}).get("advisory"),
                "runtime": round(m["runtime"] / 60) if m.get("runtime") else None,
                "release": rel,
                "synopsis": (m.get("synopsis") or (m.get("locale") or {}).get("synopsis") or "").strip(),
                "actors": list(m.get("casting") or [])[:4],
                "genres": [g.strip() for g in (m.get("genres") or "").split(",") if g.strip()] if isinstance(m.get("genres"), str) else [],
                "isEvent": False,
                "comingSoon": False,
                "links": {cid: f"https://www.cineworld.co.uk/films/{mid}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')}"},
                "shows": [],
                "bookingFrom": {},
            }
            for d, sts in (sched.get(mid) or {}).items():
                for s in sts:
                    if s.get("isExpired"):
                        continue
                    tags = [clean_tag(t) for t in s.get("tags", []) if t.startswith(("Format.", "Showtime.", "Localization."))]
                    tags = [RENAME_TAGS.get(t, t) for t in tags if t not in HIDE_TAGS]
                    url = None
                    for t in ((s.get("data") or {}).get("ticketing") or []):
                        if t.get("provider") == "default" and t.get("urls"):
                            url = t["urls"][0]
                    show = {"c": cid, "d": d, "t": s["startsAt"][11:16], "tags": tags, "sold": False}
                    if url:
                        show["u"] = url
                    rec["shows"].append(show)
                    rec["bookingFrom"].setdefault(cid, d)
            rec["shows"].sort(key=lambda s: (s["d"], s["t"]))
            if mid in soon_ids and not rec["shows"]:
                rec["comingSoon"] = True
            elif rec["release"] and start.isoformat() < rec["release"] <= soon_end:
                rec["comingSoon"] = True
            if rec["shows"] or rec["comingSoon"]:
                out.append(rec)
        return out
