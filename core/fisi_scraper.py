# core/fisi_scraper.py

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from core.race_events import RaceEvent, Federation, Discipline

URL = "https://www.asiva.it/calendario-gare/?disc=sci-alpino"


MONTHS = {
    "GEN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAG": 5,
    "GIU": 6,
    "LUG": 7,
    "AGO": 8,
    "SET": 9,
    "OTT": 10,
    "NOV": 11,
    "DIC": 12,
}


def _parse_date(raw: str, season_start: int) -> Optional[datetime]:
    try:
        # esempio: "9 DIC 2025"
        parts = raw.strip().split()
        if len(parts) != 3:
            return None

        day = int(parts[0])
        month = MONTHS.get(parts[1].upper())
        year = int(parts[2])

        if not month:
            return None

        return datetime(year, month, day)

    except Exception:
        return None


def _map_discipline(abbr: str) -> Discipline:
    abbr = abbr.upper()

    if abbr == "SL":
        return Discipline.SL
    if abbr == "GS":
        return Discipline.GS
    if abbr == "SG":
        return Discipline.SG
    if abbr == "DH":
        return Discipline.DH
    if abbr == "AC":  # combinata alpina se la trovi
        return Discipline.AC

    return Discipline.GS


def list_fisi_asiva_events(season_start: int) -> List[RaceEvent]:
    params = {
        "disc": "sci-alpino",
        "stag": f"{season_start}-{str(season_start+1)[-2:]}",
    }

    headers = {
        "User-Agent": "telemark-wax-pro/1.0",
    }

    r = requests.get(URL, params=params, headers=headers, timeout=12)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    table = soup.find("table")
    if not table:
        return []

    rows = table.find_all("tr")

    events = []

    for row in rows:
        cols = row.find_all("td")

        if len(cols) < 6:
            continue

        try:
            codex = cols[0].get_text(strip=True)
            raw_date = cols[2].get_text(strip=True)
            type_txt = cols[3].get_text(strip=True)
            spec_txt = cols[4].get_text(strip=True)
            category = cols[5].get_text(strip=True)
            name = cols[6].get_text(strip=True)

            dt = _parse_date(raw_date, season_start)
            if not dt:
                continue

            discipline = _map_discipline(spec_txt)

            # qui possiamo migliorare il place in seguito se troviamo il campo nascosto
            place = "Valle d'Aosta"

            ev = RaceEvent(
                federation=Federation.FISI,
                codex=codex,
                name=name,
                place=place,
                discipline=discipline,
                start_date=dt.date(),
                end_date=dt.date(),
                nation="ITA",
                category=category,
                raw_type=type_txt,
            )

            events.append(ev)

        except Exception:
            continue

    return events
