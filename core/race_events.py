# core/race_events.py
# Gestione calendari gare per Telemark · Pro Wax & Tune
#
# - RaceEvent: modello unico per eventi FIS / FISI
# - Federation: enum federazioni
# - FISCalendarProvider: scraping calendario Coppa del Mondo da Neveitalia
# - FISICalendarProvider: scraping calendario ASIVA (Valle d'Aosta)
# - RaceCalendarService: aggregatore, usato da streamlit_app.py

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
#  PROVIDER FIS – NEVEITALIA (Coppa del Mondo M/F)
# ---------------------------------------------------------------------------

_NEVE_MEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario"
_NEVE_WOMEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"


def _map_discipline_from_name(event_name: str) -> Discipline:
    """
    Cerca di capire la disciplina dal testo evento Neveitalia.
    Esempi:
      - 'Slalom Maschile'        -> SL
      - 'Slalom Gigante Maschile'-> GS
      - 'Super-G Maschile'       -> SG
      - 'Discesa Maschile'       -> DH
    """
    t = event_name.lower()

    if "gigante" in t:
        return Discipline.GS
    if "slalom" in t:
        return Discipline.SL
    if "super-g" in t or "super g" in t or "supergigante" in t:
        return Discipline.SG
    if "discesa" in t:
        return Discipline.DH
    if "combinata" in t:
        try:
            return Discipline.AC  # type: ignore[attr-defined]
        except Exception:
            return Discipline.GS

    # fallback
    return Discipline.GS


def _parse_neveitalia_lines(
    html: str,
    season: int,
    category_label: str,
) -> List[RaceEvent]:
    """
    Parsifica il testo di Neveitalia cercando righe tipo:

      2025-10-26 Soelden (AUT)Slalom Gigante Maschile
      2025-11-28 18:00 Copper Mountain, CO (USA)Slalom Gigante Maschile

    Logica:
      - match iniziale con data (e opzionale ora)
      - il resto è "luogo + evento"
      - usiamo l'ultima parentesi chiusa ) per separare place da nome evento
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")

    events: List[RaceEvent] = []

    # regex: data, opzionale orario, resto riga
    line_re = re.compile(
        r"^(?P<date>\d{4}-\d{2}-\d{2})(?:\s+(?P<time>\d{2}:\d{2}))?\s+(?P<rest>.+)$"
    )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = line_re.match(line)
        if not m:
            continue

        date_str = m.group("date")
        rest = m.group("rest").strip()

        # parse data
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            continue

        # filtro stagione (es: 2025-26 -> anno iniziale 2025)
        # teniamo gli eventi con anno == season o season+1
        if dt.year not in (season, season + 1):
            continue

        # separa place / event usando l'ultima ')'
        idx = rest.rfind(")")
        if idx == -1:
            # se non troviamo ')', ci rinunciamo: il formato è diverso
            continue

        place_part = rest[: idx + 1].strip()
        event_name = rest[idx + 1 :].strip()
        if not place_part or not event_name:
            continue

        # estrai nazione fra parentesi (AUT), (FIN) ecc.
        nation_match = re.search(r"\(([A-Z]{3})\)", place_part)
        nation = nation_match.group(1) if nation_match else None

        discipline = _map_discipline_from_name(event_name)

        ev = RaceEvent(
            federation=Federation.FIS,
            codex=None,  # Neveitalia non espone il codex FIS qui
            name=event_name,
            place=place_part,
            discipline=discipline,
            start_date=dt,
            end_date=dt,
            nation=nation,
            region=None,          # gare globali, nessuna regione specifica
            category=category_label,
            raw_type="CdM",
            level="WC",
        )
        events.append(ev)

    return events


class FISCalendarProvider:
    """
    Provider FIS.

    Legge il calendario di Coppa del Mondo da Neveitalia per:
      - Maschile:  _NEVE_MEN_URL
      - Femminile: _NEVE_WOMEN_URL

    NB: lo scraping dipende dal layout attuale del sito Neveitalia.
    Se cambiano il formato delle righe, questo sarà il punto da aggiornare.
    """

    USER_AGENT = "telemark-wax-pro/3.0 (FIS-Neveitalia-scraper)"

    def _fetch_html(self, url: str) -> str:
        headers = {"User-Agent": self.USER_AGENT}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return r.text

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        # Maschile
        try:
            html_m = self._fetch_html(_NEVE_MEN_URL)
            events_m = _parse_neveitalia_lines(
                html=html_m,
                season=season,
                category_label="WC-M",
            )
            events.extend(events_m)
        except Exception:
            pass

        # Femminile
        try:
            html_w = self._fetch_html(_NEVE_WOMEN_URL)
            events_w = _parse_neveitalia_lines(
                html=html_w,
                season=season,
                category_label="WC-F",
            )
            events.extend(events_w)
        except Exception:
            pass

        # filtro disciplina (stringa, es. "GS", "SL") se richiesto
        if discipline_filter:
            code = discipline_filter.strip().upper()
            events = [
                ev
                for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        # filtro nazione se richiesto
        if nation_filter:
            nf = nation_filter.strip().upper()
            events = [
                ev
                for ev in events
                if (ev.nation or "").upper() == nf
            ]

        # per ora region_filter non è usato (gare globali)
        return events


# ---------------------------------------------------------------------------
#  PROVIDER FISI (ASIVA Valle d'Aosta) – SCRAPING
#  (lasciato come nel tuo codice, lo useremo su pagina separata FISI)
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

        tbody = table.find("tbody") or table
        rows = tbody.find_all("tr")

        events: List[RaceEvent] = []

        for row in rows:
            cols = row.find_all("td")
            # struttura vista: 0=CODEX, 1=PROGR., 2=DATA, 3=TIPO, 4=SPEC., 5=PARTEC., 6=DENOMINAZIONE, ...
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
        """
        try:
            html = self._fetch_html(season_start=season)
        except Exception:
            return []

        events = self._parse_events_from_html(html, season_start=season)

        if discipline_filter:
            code = discipline_filter.strip().upper()
            events = [
                ev
                for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        return events


# ---------------------------------------------------------------------------
#  SERVIZIO AGGREGATORE
# ---------------------------------------------------------------------------

class RaceCalendarService:
    """
    Aggregatore generale per i calendari gare.

    Viene istanziato in streamlit_app.py con:
      _RACE_SERVICE = RaceCalendarService(_FIS_PROVIDER, _FISI_PROVIDER)

    list_events(...) unisce:
      - calendario FIS (Neveitalia, maschile+femminile)
      - calendario FISI (ASIVA – Valle d'Aosta)
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
        events: List[RaceEvent] = []

        # FIS (Neveitalia)
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

        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
