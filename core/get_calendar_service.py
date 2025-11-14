# core/get_calendar.py
# Parser ufficiale Neveitalia → Calendario FIS WC uomini + donne

from __future__ import annotations

import re
import datetime as dt
from dataclasses import dataclass, asdict
from html import unescape
from typing import Optional, List

import requests


NEVE_MEN = "https://www.neveitalia.it/sport/scialpino/calendario"
NEVE_WOMEN = "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"


# ---------------------------- Dataclass ----------------------------

@dataclass
class Race:
    date: str
    time: str
    location: str
    event: str
    discipline: str
    gender: str
    source: str = "neveitalia"


# ---------------------------- Utilità ------------------------------

TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: str) -> str:
    text = TAG_RE.sub("", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_date(text: str) -> tuple[str, str]:
    """
    "2025-11-16 10:00" → ("2025-11-16", "10:00")
    "2025-10-26" → ("2025-10-26", "")
    """
    parts = text.split()
    d = parts[0]
    t = parts[1] if len(parts) > 1 else ""
    return d, t


def guess_disc(text: str) -> str:
    t = text.lower()
    if "gigante" in t or "gs" in t:
        return "GS"
    if "slalom" in t and "gigante" not in t:
        return "SL"
    if "super" in t:
        return "SG"
    if "discesa" in t or "downhill" in t:
        return "DH"
    if "paralle" in t:
        return "PAR"
    return "OTHER"


# ---------------------- Estrattori blocchi HTML --------------------

BLOCK_RE = re.compile(r'<div class="ac-q".*?>(.*?)</div>', re.DOTALL)

DATE_RE = re.compile(r'<span class="date">(.*?)</span>', re.DOTALL)
PLACE_RE = re.compile(r'<span class="place">(.*?)</span>', re.DOTALL)
EVENT_RE = re.compile(r'<span class="event">(.*?)</span>', re.DOTALL)


def extract_races(html: str, gender: str) -> List[Race]:
    races = []

    for block in BLOCK_RE.findall(html):
        m_date = DATE_RE.search(block)
        m_place = PLACE_RE.search(block)
        m_event = EVENT_RE.search(block)

        if not (m_date and m_place and m_event):
            continue

        raw_date = clean_html(m_date.group(1))
        raw_place = clean_html(m_place.group(1))
        raw_event = clean_html(m_event.group(1))

        d, t = parse_date(raw_date)
        disc = guess_disc(raw_event)

        races.append(
            Race(
                date=d,
                time=t,
                location=raw_place,
                event=raw_event,
                discipline=disc,
                gender=gender,
            )
        )

    return races


# ---------------------- API pubblica ------------------------------

def get_fis_worldcup_races(
    season: int = 2025,
    gender: Optional[str] = None,
    discipline: Optional[str] = None,
) -> List[dict]:

    results: List[Race] = []

    if gender in (None, "M"):
        html = requests.get(NEVE_MEN, timeout=10).text
        results += extract_races(html, "M")

    if gender in (None, "F"):
        html = requests.get(NEVE_WOMEN, timeout=10).text
        results += extract_races(html, "F")

    # filtri stagione
    out: List[dict] = []
    for r in results:
        try:
            d = dt.date.fromisoformat(r.date)
        except:
            continue
        if d.year not in (season, season + 1):
            continue
        if discipline and r.discipline != discipline:
            continue
        out.append(asdict(r))

    # ordine per data
    out.sort(key=lambda x: x["date"])

    return out
