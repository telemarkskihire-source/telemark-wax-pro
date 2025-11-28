# core/race_events.py
# Telemark · Pro Wax & Tune
# Providers:
# - FIS: scraping NeveItalia (uomini + donne)
# - ASIVA: eventi incollati manualmente (Valle d’Aosta)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
# ENUM & MODELLO
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
# MAPPING
# ---------------------------------------------------------------------------

_MONTHS_IT = {
    "gen": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "mag": 5,
    "giu": 6,
    "lug": 7,
    "ago": 8,
    "set": 9,
    "ott": 10,
    "nov": 11,
    "dic": 12,
}


def _parse_date_it(raw: str) -> Optional[date]:
    """
    Formati supportati:
    - "9 dic 2025"
    - "10 gen 2026"
    """
    try:
        parts = raw.strip().lower().split()
        if len(parts) != 3:
            return None

        day = int(parts[0])
        month = _MONTHS_IT.get(parts[1])
        year = int(parts[2])

        if not month:
            return None

        return date(year, month, day)

    except Exception:
        return None


def _map_discipline(text: str) -> Discipline:
    t = (text or "").upper()

    if "SL" in t:
        return Discipline.SL
    if "GS" in t:
        return Discipline.GS
    if "SG" in t:
        return Discipline.SG
    if "DH" in t:
        return Discipline.DH
    if "AC" in t or "COMB" in t:
        try:
            return Discipline.AC  # type: ignore
        except Exception:
            return Discipline.GS

    return Discipline.GS


# ---------------------------------------------------------------------------
# FIS PROVIDER — NEVEITALIA
# ---------------------------------------------------------------------------

class FISCalendarProvider:
    """
    Scraping da NeveItalia:
    - Maschile: https://www.neveitalia.it/sport/scialpino/calendario
    - Femminile: https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile
    """

    BASE_URLS = [
        "https://www.neveitalia.it/sport/scialpino/calendario",
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile",
    ]

    UA = {"User-Agent": "telemark-wax-pro/4.0"}

    def _fetch(self, url: str) -> str:
        r = requests.get(url, headers=self.UA, timeout=15)
        r.raise_for_status()
        return r.text

    def _parse(self, html: str) -> List[RaceEvent]:
        soup = BeautifulSoup(html, "html.parser")

        cards = soup.find_all("div", class_="race") + soup.find_all("article")
        events: List[RaceEvent] = []

        # Metodo robusto: cerca tabelle e item ripetuti
        for row in soup.find_all("tr"):
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 4:
                continue

            try:
                raw_date = cols[0]
                place = cols[1]
                discipline = cols[2]
                name = cols[3]

                dt = _parse_date_it(raw_date)
                if not dt:
                    continue

                ev = RaceEvent(
                    federation=Federation.FIS,
                    codex=None,
                    name=name,
                    place=place,
                    discipline=_map_discipline(discipline),
                    start_date=dt,
                    end_date=dt,
                    nation=None,
                    region=None,
                    category=None,
                    raw_type="FIS",
                    level="WC",
                )

                events.append(ev)

            except Exception:
                continue

        return events

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        all_events: List[RaceEvent] = []

        for url in self.BASE_URLS:
            try:
                html = self._fetch(url)
                all_events.extend(self._parse(html))
            except Exception:
                pass

        if discipline_filter:
            code = discipline_filter.upper()
            all_events = [
                ev for ev in all_events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        return all_events


# ---------------------------------------------------------------------------
# ASIVA PROVIDER — DATI INCOLLATI (NO SCRAPING)
# ---------------------------------------------------------------------------

class ASIVACalendarProvider:

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        raw_data = [
            ("ITA0857", "9 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
            ("ITA5829", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
            ("ITA0859", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
            ("AA0001", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
            ("AA0002", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
            ("AA0003", "16 dic 2025", "SL", "Pila - Gressan", "Top 50"),
            ("AA0004", "16 dic 2025", "SL", "Pila - Gressan", "Top 50"),
            ("XA0184", "19 dic 2025", "GS", "Pila - Gressan", "Trofeo Coni"),
            ("ITA5858", "22 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
            ("ITA5862", "23 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
        ]

        events: List[RaceEvent] = []

        for codex, date_raw, spec, place, name in raw_data:

            dt = _parse_date_it(date_raw)
            if not dt:
                continue

            ev = RaceEvent(
                federation=Federation.ASIVA,
                codex=codex,
                name=name,
                place=place,
                discipline=_map_discipline(spec),
                start_date=dt,
                end_date=dt,
                nation="ITA",
                region="Valle d'Aosta",
                raw_type="ASIVA",
                level="REG",
            )

            events.append(ev)

        if discipline_filter:
            code = discipline_filter.upper()
            events = [
                ev for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        return events


# ---------------------------------------------------------------------------
# AGGREGATORE
# ---------------------------------------------------------------------------

class RaceCalendarService:

    def __init__(
        self,
        fis_provider: FISCalendarProvider,
        asiva_provider: ASIVACalendarProvider,
    ):
        self._fis = fis_provider
        self._asiva = asiva_provider

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
            try:
                events.extend(
                    self._fis.list_events(
                        season=season,
                        discipline_filter=discipline,
                    )
                )
            except Exception:
                pass

        if federation is None or federation == Federation.ASIVA:
            try:
                events.extend(
                    self._asiva.list_events(
                        season=season,
                        discipline_filter=discipline,
                    )
                )
            except Exception:
                pass

        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
