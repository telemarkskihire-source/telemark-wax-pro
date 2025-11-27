# core/race_events.py
# Calendari gare per Telemark · Pro Wax & Tune
#
# - RaceEvent: modello unico per una gara
# - Federation: FIS / FISI (label logico)
# - FISICalendarProvider: scraping da https://www.fisi.org/calendario-gare/
#   (estraiamo solo "Sci alpino")
# - FISCalendarProvider: wrapper sullo stesso calendario (per ora)
# - RaceCalendarService: unifica provider e applica filtri

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from html.parser import HTMLParser
from typing import List, Optional, Dict, Any

import re
import requests

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ---------------------- MODEL ----------------------


class Federation(str, Enum):
    FIS = "FIS"
    FISI = "FISI"


@dataclass(frozen=True)
class RaceEvent:
    start_date: date
    discipline: Optional[str]  # es. "SL", "GS", ...
    place: str
    nation: Optional[str]
    name: str                  # nome breve gara (es. "Gara internazionale")
    code: Optional[str] = None # codice gara (es. GER0741, ITA5797...)
    gender: Optional[str] = None
    federation: Federation = Federation.FISI
    raw: Dict[str, Any] = None


# ---------------------- HTML UTILS ----------------------


class _AnchorTextExtractor(HTMLParser):
    """Estrae il testo di tutti i tag <a>...</a> in una pagina HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._in_a = False
        self._current: List[str] = []
        self.texts: List[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "a":
            self._in_a = True
            self._current = []

    def handle_data(self, data: str):
        if self._in_a:
            self._current.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() == "a" and self._in_a:
            txt = "".join(self._current).strip()
            if txt:
                # normalizziamo spazi
                txt = re.sub(r"\s+", " ", txt)
                self.texts.append(txt)
            self._in_a = False
            self._current = []


def _extract_anchor_texts(html: str) -> List[str]:
    parser = _AnchorTextExtractor()
    parser.feed(html)
    return parser.texts


# ---------------------- FISI CALENDAR (fisi.org) ----------------------


class FISICalendarProvider:
    """
    Provider che legge il calendario da https://www.fisi.org/calendario-gare/
    e costruisce RaceEvent solo per "Sci alpino".
    """

    BASE_URL = "https://www.fisi.org/calendario-gare/"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(UA)

    def _fetch_html(self) -> str:
        try:
            r = self._session.get(self.BASE_URL, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception:
            return ""

    @staticmethod
    def _parse_event_from_text(txt: str) -> Optional[RaceEvent]:
        """
        Parsing di una riga tipo:

        "Sci alpino 01/11/2025 GER0741 Wittenburg - Germania M
         Gara internazionale - ENL SL - Slalom Speciale - GS GIOVANI / SENIOR"

        oppure (annullata):

        "Sci alpino 14/11/2025 Annullata ITA5797 - Italia F
         Gara internazionale - NJR GS - Slalom Gigante - G_ GIOVANI"
        """

        if not txt.startswith("Sci alpino "):
            return None

        # pattern con 'Annullata' opzionale prima del codice
        pattern = (
            r"Sci alpino\s+"
            r"(?P<date>\d{2}/\d{2}/\d{4})\s+"
            r"(?:(?:Annullata|ANNULLATA)\s+)?"
            r"(?P<code>[A-Z0-9_]+)\s+"
            r"(?P<place_country>.+?)\s+"
            r"(?P<gender>M|F|MF)\s+"
            r"(?P<desc>.+)$"
        )

        m = re.match(pattern, txt)
        if not m:
            return None

        date_str = m.group("date")
        code = m.group("code")
        place_country = m.group("place_country").strip()
        gender = m.group("gender")
        desc = m.group("desc").strip()

        # Data
        try:
            d = datetime.strptime(date_str, "%d/%m/%Y").date()
        except ValueError:
            return None

        # Place & nation (es. "Wittenburg - Germania")
        place = place_country
        nation: Optional[str] = None
        if " - " in place_country:
            before, after = place_country.split(" - ", 1)
            before = before.strip()
            after = after.strip()
            # se primo pezzo è vuoto (caso "ITA5797 - Italia"), prendi il secondo come place
            if before:
                place = before
                nation = after or None
            else:
                place = after or place
                nation = None

        # Nome gara = prima parte della descrizione prima del primo " - "
        name = desc
        if " - " in desc:
            name = desc.split(" - ", 1)[0].strip()

        # Disciplina corta: cerca SL / GS / SG / DH / AC / SC / PSL ecc. nella descrizione
        discipline = None
        disc_match = re.search(
            r"\b(SL|GS|SG|DH|AC|SC|PSL|PAR|KB)\b", desc
        )
        if disc_match:
            discipline = disc_match.group(1)

        return RaceEvent(
            start_date=d,
            discipline=discipline,
            place=place,
            nation=nation,
            name=name,
            code=code,
            gender=gender,
            federation=Federation.FISI,
            raw={"text": txt},
        )

    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,  # non usato per ora
    ) -> List[RaceEvent]:
        html = self._fetch_html()
        if not html:
            return []

        texts = _extract_anchor_texts(html)

        events: List[RaceEvent] = []
        for txt in texts:
            if not txt.startswith("Sci alpino "):
                continue
            ev = self._parse_event_from_text(txt)
            if ev is None:
                continue

            # filtro stagione: accetta stagione ±1 per sicurezza
            if ev.start_date.year not in {season - 1, season, season + 1}:
                continue

            events.append(ev)

        # filtri aggiuntivi opzionali
        if discipline:
            d_up = discipline.upper()
            events = [
                e for e in events
                if e.discipline and e.discipline.upper() == d_up
            ]

        if nation:
            n_low = nation.lower()
            events = [
                e for e in events
                if e.nation and n_low in e.nation.lower()
            ]

        # nessun filtro su region per ora

        return events


# ---------------------- FIS CALENDAR (wrapper) ----------------------


class FISCalendarProvider:
    """
    Per ora usiamo lo stesso calendario FISI come sorgente dati.
    In futuro si potrà collegare un feed FIS separato (Neveitalia, FIS API, ecc.).
    """

    def __init__(self, fisi_provider: Optional[FISICalendarProvider] = None) -> None:
        self._fisi = fisi_provider or FISICalendarProvider()

    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        # delega a FISI, per non lasciare vuota la sezione FIS
        events = self._fisi.list_events(
            season=season,
            discipline=discipline,
            nation=nation,
            region=region,
        )
        # NON cambiamo federation per non complicare troppo:
        # in UI al momento la federation non viene mostrata.
        return events


# ---------------------- SERVICE ----------------------


class RaceCalendarService:
    """
    Punto unico di accesso per il calendario gare dell'app.
    Unisce provider FIS / FISI e applica i filtri richiesti dallo streamlit_app.
    """

    def __init__(
        self,
        fis_provider: Optional[FISCalendarProvider] = None,
        fisi_provider: Optional[FISICalendarProvider] = None,
    ) -> None:
        self._fis_provider = fis_provider or FISCalendarProvider()
        self._fisi_provider = fisi_provider or FISICalendarProvider()

    def list_events(
        self,
        season: int,
        federation: Optional[Federation] = None,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        # Se "Tutte", federation è None → prendiamo entrambi i provider
        if federation is None or federation == Federation.FIS:
            events.extend(
                self._fis_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            )

        if federation is None or federation == Federation.FISI:
            events.extend(
                self._fisi_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            )

        # Deduplica (caso FIS/FISI che leggono la stessa sorgente)
        unique: Dict[tuple, RaceEvent] = {}
        for e in events:
            key = (e.code, e.start_date, e.place, e.name)
            unique[key] = e

        out = list(unique.values())
        out.sort(key=lambda e: (e.start_date, e.place, e.name))
        return out
