# core/race_events.py
# Calendari gare per Telemark · Pro Wax & Tune
# - FIS: scraping Neveitalia (maschile + femminile)
# - ASIVA: parsing diretto da testo fornito (Valle d'Aosta)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import List, Optional
import re
import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
# MODELLO BASE
# ---------------------------------------------------------------------------

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
    category: Optional[str] = None
    raw_type: Optional[str] = None
    level: Optional[str] = None

    @property
    def is_future(self) -> bool:
        return self.start_date >= date.today()


# ---------------------------------------------------------------------------
# FIS – NEVEITALIA (maschile + femminile)
# ---------------------------------------------------------------------------

NEVEITALIA_M = "https://www.neveitalia.it/sport/scialpino/calendario"
NEVEITALIA_F = "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"

MONTHS = {
    "GEN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAG": 5, "GIU": 6,
    "LUG": 7, "AGO": 8, "SET": 9, "OTT": 10, "NOV": 11, "DIC": 12
}

UA = {"User-Agent": "telemark-wax-pro/4.0"}

def _guess_discipline(text: str) -> Discipline:
    t = text.upper()
    if "SLALOM" in t:
        return Discipline.SL
    if "GIGANTE" in t:
        return Discipline.GS
    if "SUPER" in t or "SUPERG" in t:
        return Discipline.SG
    if "DISCESA" in t or "DOWNHILL" in t:
        return Discipline.DH
    return Discipline.GS


def _parse_neveitalia_html(html: str, gender: str) -> List[RaceEvent]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 5]

    events: List[RaceEvent] = []

    date_regex = re.compile(r"(\d{1,2})\s([A-Z]{3})\s(\d{4})")

    current_date = None

    for line in lines:

        # cerca data
        m = date_regex.search(line)
        if m:
            day = int(m.group(1))
            month = MONTHS.get(m.group(2))
            year = int(m.group(3))

            if month:
                current_date = date(year, month, day)
            else:
                current_date = None
            continue

        if not current_date:
            continue

        # Possibile formato:
        # "Val d’Isere (FRA) – Slalom Gigante Maschile"
        if ("(" in line and ")" in line) and len(line) < 120:
            place = line.split("–")[0].strip()
            name = line.strip()

            ev = RaceEvent(
                federation=Federation.FIS,
                codex=None,
                name=f"{name} ({gender})",
                place=place,
                discipline=_guess_discipline(name),
                start_date=current_date,
                end_date=current_date,
                nation=None,
                region=None,
                category=gender,
                raw_type="WC",
                level="WORLD_CUP",
            )

            events.append(ev)

    return events


class FISCalendarProvider:

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        events = []

        try:
            r1 = requests.get(NEVEITALIA_M, headers=UA, timeout=12)
            r2 = requests.get(NEVEITALIA_F, headers=UA, timeout=12)

            r1.raise_for_status()
            r2.raise_for_status()

            events += _parse_neveitalia_html(r1.text, "M")
            events += _parse_neveitalia_html(r2.text, "F")

        except Exception:
            return []

        # filtro stagione
        events = [e for e in events if e.start_date.year in (season, season + 1)]

        # filtro disciplina
        if discipline_filter:
            code = discipline_filter.upper()
            events = [e for e in events if e.discipline and e.discipline.value.upper() == code]

        return events


# ---------------------------------------------------------------------------
# ASIVA – parsing diretto dal tuo testo
# ---------------------------------------------------------------------------

ASIVA_RAW_TEXT = """
ITA0857  9 dic 2025 FIS_NJR GS M Courmayeur Trofeo ODL
ITA5829  10 dic 2025 FIS_NJR GS F Courmayeur Trofeo ODL
ITA0859  10 dic 2025 FIS_NJR GS M Courmayeur Trofeo ODL
AA0001   16 dic 2025 PM_REG GS Pila - Gressan Top 50
AA0002   16 dic 2025 PM_REG GS Pila - Gressan Top 50
AA0003   16 dic 2025 PM_REG SL Pila - Gressan Top 50
AA0004   16 dic 2025 PM_REG SL Pila - Gressan Top 50
AA0005   17 dic 2025 PM_REG SL Pila - Gressan Top 50
AA0006   17 dic 2025 PM_REG SL Pila - Gressan Top 50
AA0007   17 dic 2025 PM_REG GS Pila - Gressan Top 50
AA0008   17 dic 2025 PM_REG GS Pila - Gressan Top 50
"""

ASIVA_DATE_RE = re.compile(r"(\d{1,2})\s(dic|gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov)\s(2025|2026)", re.IGNORECASE)

def _parse_asiva() -> List[RaceEvent]:
    events = []

    for line in ASIVA_RAW_TEXT.splitlines():
        line = line.strip()
        if len(line) < 10:
            continue

        parts = re.split(r"\s{2,}|\t", line)

        if not parts:
            continue

        codex = parts[0].strip()
        date_match = ASIVA_DATE_RE.search(line)
        if not date_match:
            continue

        day = int(date_match.group(1))
        month = MONTHS.get(date_match.group(2).upper())
        year = int(date_match.group(3))

        if not month:
            continue

        d = date(year, month, day)

        place = ""
        if "Courmayeur" in line:
            place = "Courmayeur"
        elif "Pila" in line:
            place = "Pila - Gressan"
        elif "La Thuile" in line:
            place = "La Thuile"
        elif "Valtournenche" in line:
            place = "Valtournenche"
        elif "Frachey" in line or "Ayas" in line:
            place = "Frachey - Ayas"
        elif "Torgnon" in line:
            place = "Torgnon"
        else:
            place = "Valle d'Aosta"

        discipline = Discipline.GS if "GS" in line else Discipline.SL

        ev = RaceEvent(
            federation=Federation.ASIVA,
            codex=codex,
            name=line,
            place=place,
            discipline=discipline,
            start_date=d,
            end_date=d,
            nation="ITA",
            region="Valle d'Aosta",
            category=None,
            raw_type="ASIVA",
            level="REGIONAL",
        )

        events.append(ev)

    return events


class ASIVACalendarProvider:

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        events = _parse_asiva()
        events = [e for e in events if e.start_date.year in (season, season + 1)]

        if discipline_filter:
            code = discipline_filter.upper()
            events = [e for e in events if e.discipline and e.discipline.value.upper() == code]

        return events


# ---------------------------------------------------------------------------
# AGGREGATORE
# ---------------------------------------------------------------------------

class RaceCalendarService:

    def __init__(self):
        self._fis = FISCalendarProvider()
        self._asiva = ASIVACalendarProvider()

    def list_events(
        self,
        season: int,
        federation: Optional[Federation] = None,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:

        events: List[RaceEvent] = []

        if federation is None or federation == Federation.FIS:
            events += self._fis.list_events(season, discipline)

        if federation is None or federation == Federation.ASIVA:
            events += self._asiva.list_events(season, discipline)

        events.sort(key=lambda e: (e.start_date, e.place))
        return events
