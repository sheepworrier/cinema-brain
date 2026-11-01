"""Interface every cinema source implements. Add new cinemas by writing another Source."""
from __future__ import annotations

from datetime import date


class Source:
    cinema: dict  # {"id", "name", "url"}

    def fetch(self, start: date, days: int, soon_days: int) -> list[dict]:
        """Return Film dicts (see model.py) for films showing in [start, start+days) and
        films released in (start, start+soon_days]."""
        raise NotImplementedError
