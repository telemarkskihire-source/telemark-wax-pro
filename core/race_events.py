# core/race_events.py
# Telemark · Pro Wax & Tune
# Providers:
# - FIS: scraping NeveItalia (uomini + donne)
# - ASIVA: eventi incollati manualmente (Valle d’Aosta)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional
import re

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
# SUPPORTO DATE / DISCIPLINE
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


def _map_discipline_from_text(text: str) -> Discipline:
    t = (text or "").lower()

    if "gigante" in t or "giant" in t:
        return Discipline.GS
    if "slalom" in t:
        return Discipline.SL
    if "super-g" in t or "super g" in t or "super g " in t:
        return Discipline.SG
    if "discesa" in t or "downhill" in t:
        return Discipline.DH
    if "comb" in t:
        try:
            return Discipline.AC  # type: ignore[attr-defined]
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

    _LINE_RE = re.compile(
        r"^(?P<date>\d{4}-\d{2}-\d{2})"
        r"(?:\s+(?P<time>\d{2}:\d{2}))?\s+"
        r"(?P<rest>.+)$"
    )

    def _fetch(self, url: str) -> str:
        r = requests.get(url, headers=self.UA, timeout=15)
        r.raise_for_status()
        return r.text

    def _parse(self, html: str, season: int) -> List[RaceEvent]:
        soup = BeautifulSoup(html, "html.parser")

        # prendiamo TUTTO il testo e lavoriamo per righe
        text = soup.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        events: List[RaceEvent] = []

        for ln in lines:
            if not ln.startswith("20"):
                continue

            m = self._LINE_RE.match(ln)
            if not m:
                continue

            date_str = m.group("date")
            rest = m.group("rest")

            try:
                year, month, day = map(int, date_str.split("-"))
                dt = date(year, month, day)
            except Exception:
                continue

            # filtro stagione: anno = season o season+1
            if not (season <= dt.year <= season + 1):
                continue

            # rest es: "Levi (FIN)Slalom Maschile"
            place = rest
            name = ""

            idx = rest.rfind(")")
            if idx != -1:
                place = rest[: idx + 1].strip()
                name = rest[idx + 1 :].strip()
            else:
                # fallback: prima parola come place, resto come name
                parts = rest.split(maxsplit=1)
                if len(parts) == 2:
                    place, name = parts[0], parts[1]
                else:
                    place = rest
                    name = rest

            discipline = _map_discipline_from_text(name)

            ev = RaceEvent(
                federation=Federation.FIS,
                codex=None,
                name=name,
                place=place,
                discipline=discipline,
                start_date=dt,
                end_date=dt,
                nation=None,
                region=None,
                category=None,
                raw_type="FIS",
                level="WC",
            )
            events.append(ev)

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
                all_events.extend(self._parse(html, season=season))
            except Exception:
                # se una delle due pagine fallisce, continuiamo con l’altra
                continue

        if discipline_filter:
            code = discipline_filter.upper()
            all_events = [
                ev
                for ev in all_events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        return all_events


# ---------------------------------------------------------------------------
# ASIVA PROVIDER — DATI INCOLLATI (NO SCRAPING)
# ---------------------------------------------------------------------------

class ASIVACalendarProvider:
    """
    Calendario ASIVA (sci alpino) incollato a mano dalla tabella ufficiale.
    Qui NON facciamo scraping: è un database locale facile da mantenere.
    """

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        # codex, data, spec, località, denominazione
        raw_data = [
            ("ITA0857", "9 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
            ("ITA5829", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
            ("ITA0859", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
            ("AA0001", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
            ("AA0002", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
            ("AA0003", "16 dic 2025", "SL", "Pila - Gressan", "Top 50"),
            ("AA0004", "16 dic 2025", "SL", "Pila - Gressan", "Top 50"),
            ("AA0005", "17 dic 2025", "SL", "Pila - Gressan", "Top 50"),
            ("AA0006", "17 dic 2025", "SL", "Pila - Gressan", "Top 50"),
            ("AA0007", "17 dic 2025", "GS", "Pila - Gressan", "Top 50"),
            ("AA0008", "17 dic 2025", "GS", "Pila - Gressan", "Top 50"),
            ("XA0184", "19 dic 2025", "GS", "Pila - Gressan", "Trofeo Coni"),
            ("XA0185", "19 dic 2025", "GS", "Pila - Gressan", "Trofeo Coni"),
            ("XA0186", "20 dic 2025", "SL", "Pila - Gressan", "Trofeo Coni"),
            ("XA0187", "20 dic 2025", "SL", "Pila - Gressan", "Trofeo Coni"),
            ("ITA5851", "20 dic 2025", "SL", "La Thuile", "Memorial Menel"),
            ("ITA0883", "20 dic 2025", "SL", "La Thuile", "Memorial Menel"),
            ("ITA5855", "21 dic 2025", "SL", "La Thuile", "Memorial Menel"),
            ("ITA0887", "21 dic 2025", "SL", "La Thuile", "Memorial Menel"),
            ("AA0009", "21 dic 2025", "SL", "Valtournenche", "Trofeo Igor Gorgonzola Flipper"),
            ("AA0010", "21 dic 2025", "SL", "Valtournenche", "Trofeo Igor Gorgonzola Flipper"),
            ("AA0011", "22 dic 2025", "SL", "La Thuile", "Memorial Edoardo Camardella"),
            ("AA0012", "22 dic 2025", "SL", "La Thuile", "Memorial Edoardo Camardella"),
            ("ITA5858", "22 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
            ("ITA0890", "22 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
            ("ITA5862", "23 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
            ("ITA0894", "23 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
            ("AA0013", "23 dic 2025", "SL", "Pila - Gressan", "Coppa Valle d'Aosta Spettacolo Flipper"),
            ("AA0014", "23 dic 2025", "SL", "Pila - Gressan", "Coppa Valle d'Aosta Spettacolo Flipper"),
            ("AA0015", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0020", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0017", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0022", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0018", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0023", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0016", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0021", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0019", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
            ("AA0024", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ]

        events: List[RaceEvent] = []

        for codex, date_raw, spec, place, name in raw_data:
            dt = _parse_date_it(date_raw)
            if not dt:
                continue

            # semplice filtro stagione
            if not (season <= dt.year <= season + 1):
                continue

            ev = RaceEvent(
                federation=Federation.ASIVA,
                codex=codex,
                name=name,
                place=place,
                discipline=_map_discipline_from_text(spec),
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
