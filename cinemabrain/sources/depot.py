"""Depot, Lewes: parse the static calendar page at lewesdepot.org/whats-on/calendar."""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta

from ..util import ROOT, http_get, norm_cert

BASE = "https://lewesdepot.org"
TITLES = ROOT / "cache" / "depot_titles.json"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}

TOKEN = re.compile(
    r'<div class="film-calendar-day[^"]*"><div class="contents"><h2>(?P<day>.*?)</h2>'
    r'|<div class="film-calendar-film"\s+data-sid="(?P<sid>\d+)"\s+data-link="(?P<link>[^"]+)"\s*>'
    r'<div class="contents"><h3>(?P<title>.*?)</h3>(?P<rest>.*?)</div></div>',
    re.S,
)


class DepotSource:
    def __init__(self):
        self.cinema = {"id": "lewes-depot", "name": "Depot, Lewes", "url": f"{BASE}/whats-on/calendar"}

    def _full_title(self, link: str, shown: str, cache: dict) -> str:
        if not shown.endswith("..."):
            return shown
        if link in cache:
            return cache[link]
        try:
            page = http_get(BASE + link, timeout=30).decode("utf-8", "ignore")
            m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) or re.search(r'og:title" content="([^"]+)"', page)
            title = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else shown
            title = re.sub(r"\s+", " ", re.sub(r"\s*[|–-]\s*Depot.*$", "", title)).strip() or shown
        except Exception:
            return shown.rstrip(".").strip()
        cache[link] = title
        return title

    def fetch(self, start: date, days: int = 7, soon_days: int = 31) -> list[dict]:
        cid = self.cinema["id"]
        page = http_get(BASE + "/whats-on/calendar", timeout=60).decode("utf-8", "ignore")
        cache = json.loads(TITLES.read_text()) if TITLES.exists() else {}
        win_end = (start + timedelta(days=days)).isoformat()
        soon_end = (start + timedelta(days=soon_days)).isoformat()

        films: dict[str, dict] = {}
        cur: date | None = None
        for m in TOKEN.finditer(page):
            if m.group("day"):
                txt = html.unescape(re.sub(r"<[^>]+>", " ", m.group("day"))).strip()
                mm = re.search(r"(\d{1,2})\s+([A-Za-z]+)", txt)
                if not mm or mm.group(2).lower() not in MONTHS:
                    continue
                mon = MONTHS[mm.group(2).lower()]
                year = start.year + (1 if mon < start.month - 1 else 0)
                cur = date(year, mon, int(mm.group(1)))
                continue
            if cur is None:
                continue
            link = m.group("link")
            title = html.unescape(re.sub(r"<[^>]+>", "", m.group("title"))).strip()
            rest = m.group("rest")
            cert = norm_cert((re.search(r"Cert:\s*([A-Za-z0-9]+)", rest) or [None, None])[1])
            times = re.findall(r'class="[^"]*btn-perf[^"]*"[^>]*>\s*(\d{1,2}:\d{2})\s*<', rest)
            f = films.get(link)
            if f is None:
                f = films[link] = {
                    "key": f"{cid}:{link.rsplit('/', 1)[-1]}",
                    "title": title,  # resolved below if truncated
                    "_link": link,
                    "cert": cert,
                    "certNote": None,
                    "runtime": None,
                    "release": None,
                    "synopsis": "",
                    "actors": [],
                    "genres": [],
                    "isEvent": False,
                    "comingSoon": False,
                    "links": {cid: BASE + link},
                    "shows": [],
                    "bookingFrom": {},
                }
            ds = cur.isoformat()
            f["bookingFrom"].setdefault(cid, ds)
            if ds >= start.isoformat():
                for t in times:
                    f["shows"].append({"c": cid, "d": ds, "t": t.zfill(5), "tags": [], "sold": False})

        out = []
        for f in films.values():
            f["title"] = self._full_title(f.pop("_link"), f["title"], cache)
            in_window = [s for s in f["shows"] if s["d"] < win_end]
            first = f["bookingFrom"].get(cid)
            f["shows"] = in_window
            if not in_window and first and win_end <= first <= soon_end:
                f["comingSoon"] = True
                f["release"] = first
            if in_window or f["comingSoon"]:
                f["shows"].sort(key=lambda s: (s["d"], s["t"]))
                out.append(f)
        TITLES.parent.mkdir(exist_ok=True)
        TITLES.write_text(json.dumps(cache, indent=1))
        return out
