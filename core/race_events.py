# core/race_events.py

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


class Federation(str, Enum):
    FIS = "FIS"
    ASIVA = "ASIVA"


@dataclass
class RaceEvent:
    federation: Federation
    codex: Optional[str]
    name: str
    place: str
    discipline: Optional[Discipline]
    start_date: date
    end_date: date
    nation: Optional[str] = None
    region: Optional[str] = None
    raw_type: Optional[str] = None


_MONTHS_IT = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4,
    "mag": 5, "giu": 6, "lug": 7, "ago": 8,
    "set": 9, "ott": 10, "nov": 11, "dic": 12,
}


def _parse_date_it(raw: str) -> Optional[date]:
    try:
        parts = raw.strip().lower().split()
        if len(parts) != 3:
            return None
        return date(int(parts[2]), _MONTHS_IT.get(parts[1], 0), int(parts[0]))
    except:
        return None


def _map_discipline(text: str) -> Discipline:
    t = (text or "").upper()
    if "SL" in t: return Discipline.SL
    if "GS" in t: return Discipline.GS
    if "SG" in t: return Discipline.SG
    if "DH" in t: return Discipline.DH
    return Discipline.GS


class FISCalendarProvider:

    URLS = [
        "https://www.neveitalia.it/sport/scialpino/calendario",
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile",
    ]

    def list_events(self, season: int, discipline_filter=None, **_):

        events = []

        for url in self.URLS:
            try:
                html = requests.get(url, headers={"User-Agent":"telemark"}).text
                soup = BeautifulSoup(html, "html.parser")

                for card in soup.find_all(["article","div"], class_=["gara","race"]):

                    txt = card.get_text(" ", strip=True)

                    # Cerca data
                    dt = None
                    for m in _MONTHS_IT.keys():
                        if m in txt.lower():
                            parts = txt.lower().split(m)
                            left = parts[0].strip().split()[-1]
                            year = parts[1].strip().split()[0]
                            dt = _parse_date_it(f"{left} {m} {year}")
                            break

                    if not dt:
                        continue

                    # Discipline
                    disc = _map_discipline(txt)

                    # Nome e luogo
                    place = None
                    name = "FIS Race"

                    if "-" in txt:
                        pt = txt.split("-")
                        place = pt[0].strip()

                    if not place:
                        # fallback
                        place = txt.replace(str(dt.year),"").strip()

                    ev = RaceEvent(
                        federation=Federation.FIS,
                        codex=None,
                        name=name,
                        place=place,
                        discipline=disc,
                        start_date=dt,
                        end_date=dt,
                        nation=None,
                    )

                    if not discipline_filter or (ev.discipline and ev.discipline.value == discipline_filter):
                        events.append(ev)

            except:
                continue

        return events


class ASIVACalendarProvider:

    RAW_DATA = [
        ("ITA0857", "9 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
        ("ITA5829", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
        ("AA0001", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
        ("AA0009", "21 dic 2025", "SL", "Valtournenche", "Trofeo Igor"),
        ("ITA5858", "22 dic 2025", "GS", "Frachey - Ayas", "Pulverit"),
        ("ITA5862", "23 dic 2025", "GS", "Frachey - Ayas", "Pulverit"),
        ("AA0015", "23 dic 2025", "GS", "Torgnon", "Trofeo Torgnon"),
    ]

    def list_events(self, season:int, discipline_filter=None, month_filter=None, **_):

        events = []

        for codex, dte, spec, place, name in self.RAW_DATA:
            dt = _parse_date_it(dte)
            if not dt: continue

            if month_filter and dt.month != month_filter:
                continue

            disc = _map_discipline(spec)

            if discipline_filter and disc.value != discipline_filter:
                continue

            events.append(RaceEvent(
                federation=Federation.ASIVA,
                codex=codex,
                name=name,
                place=place,
                discipline=disc,
                start_date=dt,
                end_date=dt,
                nation="ITA",
                region="Valle d'Aosta"
            ))

        return events


class RaceCalendarService:

    def __init__(self, fis: FISCalendarProvider, asiva: ASIVACalendarProvider):
        self.fis = fis
        self.asiva = asiva

    def list_events(self, season, federation=None, discipline=None, month=None, **_):

        events = []

        if federation in [None, Federation.FIS]:
            events += self.fis.list_events(season, discipline)

        if federation in [None, Federation.ASIVA]:
            events += self.asiva.list_events(season, discipline, month_filter=month)

        events.sort(key=lambda x: x.start_date)
        return events
