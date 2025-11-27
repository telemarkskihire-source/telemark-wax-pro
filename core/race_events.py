# core/race_events.py
# Gestione calendari gare per Telemark · Pro Wax & Tune
#
# - RaceEvent: modello unico per eventi FIS / FISI
# - Federation: enum federazioni
# - FISCalendarProvider: placeholder (da collegare a FIS / Neveitalia)
# - FISICalendarProvider: scraping calendario ASIVA (Valle d'Aosta)
# - RaceCalendarService: aggregatore, usato da streamlit_app.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
#  ENUM & MODELLO DI BASE
# ---------------------------------------------------------------------------

class Federation(str, Enum):
    FIS = "FIS"
    FISI = "FISI"


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
#  PROVIDER FIS – (placeholder, da completare se/quando serve)
# ---------------------------------------------------------------------------

class FISCalendarProvider:
    """
    Provider FIS.

    Al momento è un placeholder che restituisce una lista vuota.
    L'idea è di collegarlo in futuro a:
    - API ufficiali FIS
    - oppure scraping/JSON Neveitalia (come versione precedente)
    """

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:
        # TODO: implementare collegamento reale al calendario FIS
        return []


# ---------------------------------------------------------------------------
#  PROVIDER FISI (ASIVA Valle d'Aosta) – SCRAPING
# ---------------------------------------------------------------------------

ASIVA_BASE_URL = "https://www.asiva.it/calendario-gare/"

_MONTHS_IT_SHORT = {
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


def _parse_asiva_date(raw: str, season_start: int) -> Optional[date]:
    """
    Converte una data ASIVA stile '9 DIC 2025' in oggetto date.
    """
    try:
        parts = raw.strip().split()
        if len(parts) != 3:
            return None

        day = int(parts[0])
        month = _MONTHS_IT_SHORT.get(parts[1].upper())
        year = int(parts[2])

        if not month:
            return None

        return date(year, month, day)
    except Exception:
        return None


def _map_discipline_from_spec(abbr: str) -> Discipline:
    """
    Converte SPEC. (GS, SL, SG, DH, AC, ...) nel nostro enum Discipline.
    Se non riconosciuto, default = GS.
    """
    code = (abbr or "").strip().upper()

    if code == "SL":
        return Discipline.SL
    if code == "GS":
        return Discipline.GS
    if code == "SG":
        return Discipline.SG
    if code == "DH":
        return Discipline.DH
    if code in {"AC", "SC", "COMBI"}:
        # combinata: usa AC se esiste nel tuo enum, altrimenti GS
        try:
            return Discipline.AC  # type: ignore[attr-defined]
        except Exception:
            return Discipline.GS

    return Discipline.GS


class FISICalendarProvider:
    """
    Provider FISI basato sul calendario ASIVA (Valle d'Aosta).

    Sito di riferimento (come da tua indicazione):
    https://www.asiva.it/calendario-gare/?disc=sci-alpino&stag=2025-26

    NOTA: lo scraping è fragile per natura; se in futuro il layout cambia,
    qui sarà il punto da aggiornare.
    """

    USER_AGENT = "telemark-wax-pro/3.0 (FISI-ASIVA-scraper)"

    def _fetch_html(self, season_start: int) -> str:
        params = {
            "disc": "sci-alpino",
            "stag": f"{season_start}-{str(season_start + 1)[-2:]}",
        }
        headers = {"User-Agent": self.USER_AGENT}

        r = requests.get(ASIVA_BASE_URL, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        return r.text

    def _parse_events_from_html(self, html: str, season_start: int) -> List[RaceEvent]:
        soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table")
        if not table:
            return []

        # usiamo tbody se presente, altrimenti tutte le tr
        tbody = table.find("tbody") or table
        rows = tbody.find_all("tr")

        events: List[RaceEvent] = []

        for row in rows:
            cols = row.find_all("td")
            # struttura vista nello screenshot:
            # 0=CODEX, 1=PROGR., 2=DATA, 3=TIPO, 4=SPEC., 5=PARTEC., 6=DENOMINAZIONE, ...
            if len(cols) < 7:
                continue

            try:
                codex = cols[0].get_text(strip=True) or None
                raw_date = cols[2].get_text(strip=True)
                tipo = cols[3].get_text(strip=True) or None
                spec = cols[4].get_text(strip=True) or ""
                category = cols[5].get_text(strip=True) or None
                name = cols[6].get_text(strip=True) or ""

                dt = _parse_asiva_date(raw_date, season_start)
                if not dt:
                    continue

                discipline = _map_discipline_from_spec(spec)

                # Nel calendario ASIVA il luogo è implicito: per ora fissiamo
                # Valle d'Aosta come place generico. In futuro si può leggere
                # da eventuali colonne/tooltip aggiuntivi.
                place = "Valle d'Aosta"

                ev = RaceEvent(
                    federation=Federation.FISI,
                    codex=codex,
                    name=name,
                    place=place,
                    discipline=discipline,
                    start_date=dt,
                    end_date=dt,
                    nation="ITA",
                    region="Valle d'Aosta",
                    category=category,
                    raw_type=tipo,
                    level=None,
                )
                events.append(ev)

            except Exception:
                # se una singola riga fallisce, proseguiamo con le altre
                continue

        return events

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:
        """
        Ritorna le gare ASIVA/FISI per la stagione indicata.

        discipline_filter: stringa come "GS", "SL" ecc. (come in streamlit_app)
        nation_filter / region_filter al momento non usati (Valle d'Aosta fissa).
        """
        try:
            html = self._fetch_html(season_start=season)
        except Exception:
            return []

        events = self._parse_events_from_html(html, season_start=season)

        # filtro disciplina (stringa, es. "GS") se richiesto
        if discipline_filter:
            code = discipline_filter.strip().upper()
            events = [
                ev
                for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        # se un domani vorrai filtrare per nazione/regione, puoi farlo qui
        return events


# ---------------------------------------------------------------------------
#  SERVIZIO AGGREGATORE
# ---------------------------------------------------------------------------

class RaceCalendarService:
    """
    Aggregatore generale per i calendari gare.

    Viene istanziato in streamlit_app.py con:
      _RACE_SERVICE = RaceCalendarService(_FIS_PROVIDER, _FISI_PROVIDER)

    Il metodo principale è list_events(…).
    """

    def __init__(
        self,
        fis_provider: FISCalendarProvider,
        fisi_provider: FISICalendarProvider,
    ):
        self._fis = fis_provider
        self._fisi = fisi_provider

    def list_events(
        self,
        season: int,
        federation: Optional[Federation] = None,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        """
        Restituisce la lista di RaceEvent per:
          - stagione (anno iniziale)
          - federazione (FIS, FISI o None = entrambe)
          - disciplina (stringa tipo "GS", "SL"... oppure None)
          - filtri nazione/regione (per ora usati solo a livello logico)
        """
        events: List[RaceEvent] = []

        # FIS
        if federation is None or federation == Federation.FIS:
            try:
                events_fis = self._fis.list_events(
                    season=season,
                    discipline_filter=discipline,
                    nation_filter=nation,
                    region_filter=region,
                )
                events.extend(events_fis)
            except Exception:
                # se FIS fallisce, non blocchiamo tutto
                pass

        # FISI (ASIVA)
        if federation is None or federation == Federation.FISI:
            try:
                events_fisi = self._fisi.list_events(
                    season=season,
                    discipline_filter=discipline,
                    nation_filter=nation,
                    region_filter=region,
                )
                events.extend(events_fisi)
            except Exception:
                pass

        # Ordina per data (e, secondariamente, per nome)
        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
