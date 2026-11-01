"""Small shared helpers: HTTP, .env loading, title normalisation."""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) CinemaBrain/1.0"


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def http_get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_json(url: str, headers: dict | None = None) -> dict:
    return json.loads(http_get(url, {"Accept": "application/json", **(headers or {})}))


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s


def norm_title(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


CERT_MAP = {"U": "U", "UC": "U", "PG": "PG", "12A": "12A", "12": "12A", "15": "15", "18": "18", "R18": "18"}


def norm_cert(c: str | None) -> str:
    """Normalise a certificate string to U / PG / 12A / 15 / 18 / TBC."""
    return CERT_MAP.get((c or "").strip().upper().replace(" ", ""), "TBC")


def clean_tag(t: str) -> str:
    """'Format.Experience.ScreenX' -> 'ScreenX'; 'ScreenX' stays; CamelCase -> words."""
    import re as _re
    last = t.split(".")[-1]
    return _re.sub(r"(?<=[a-z])(?=[A-Z])", " ", last).strip()
