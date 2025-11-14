# core/race_events.py
#
# Calendari gare per Telemark · Pro Wax & Tune
# - FIS: parsing da Neveitalia (Coppa del Mondo maschile + femminile)
# - FISI: placeholder (Neveitalia non espone calendari strutturati FISI/comitati)

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List, Callable, Dict

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------
# ENUM / COSTANTI BASE (per ora semplici stringhe)
# ---------------------------------------------------------

class Federation:
    FIS = "FIS"
    FISI = "FISI"


class Discipline:
    SL = "SL"
    GS = "GS"
    SG = "SG"
    DH = "DH"


# ---------------------------------------------------------
# DATACLASS EVENTO
# ---------------------------------------------------------

@dataclass
class RaceEvent:
    federation: str
    season: int
    discipline: Optional[str]
    code: str
    name: str
    nation: Optional[str]
    region: Optional[str]
    place: str
    resort: Optional[str]
    start_date: date
    end_date: date
    category: Optional[str]
    level: Optional[str]
    gender: Optional[str]
    source_url: str


# ---------------------------------------------------------
# PROVIDER BASE
# ---------------------------------------------------------

class BaseCalendarProvider:
    federation: str = ""

    def fetch_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
        category: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[RaceEvent]:
        raise NotImplementedError


# ---------------------------------------------------------
# FIS / NEVEITALIA — WORLD CUP MASCHILE + FEMMINILE
# ---------------------------------------------------------

class FISCalendarProvider(BaseCalendarProvider):
    """
    Provider FIS che usa Neveitalia come sorgente per i calendari
    di Coppa del Mondo (maschile + femminile).

    NOTE:
    - lavora su:
      * https://www.neveitalia.it/sport/scialpino/calendario
      * https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile
    - non esistono codici FIS ufficiali in pagina → code sintetico NEVE-...
    - category/level fissati a 'WC'.
    """

    federation = Federation.FIS

    BASE_URL_MEN = "https://www.neveitalia.it/sport/scialpino/calendario"
    BASE_URL_WOMEN = (
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"
    )

    def __init__(self, http_client: Callable[[str, Optional[dict]], str]):
        """
        http_client: funzione tipo (url, params) -> text
        (requests.get(url, params=...) .text)
        """
        self.http_client = http_client

    # ------------------ API pubblica ------------------

    def fetch_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
        category: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        # maschile
        try:
            html_men = self.http_client(self.BASE_URL_MEN, {})
            events += self._parse_neveitalia_html(
                html=html_men,
                season=season,
                discipline_filter=discipline,
                gender="M",
                source_url=self.BASE_URL_MEN,
            )
        except Exception:
            pass

        # femminile
        try:
            html_women = self.http_client(self.BASE_URL_WOMEN, {})
            events += self._parse_neveitalia_html(
                html=html_women,
                season=season,
                discipline_filter=discipline,
                gender="F",
                source_url=self.BASE_URL_WOMEN,
            )
        except Exception:
            pass

        # filtra per nazione se richiesto (NaCod tipo ITA)
        if nation:
            events = [e for e in events if (e.nation or "").upper() == nation.upper()]

        # ordina per data
        events.sort(key=lambda ev: ev.start_date)
        return events

    # ------------------ parsing Neveitalia ------------------

    DATE_LINE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:\s+(?P<time>\d{2}:\d{2}))?\s+(?P<rest>.+)$")

    def _parse_neveitalia_html(
        self,
        html: str,
        season: int,
        discipline_filter: Optional[str],
        gender: Optional[str],
        source_url: str,
    ) -> List[RaceEvent]:
        """
        Estrapola righe tipo:
            2025-10-26 Soelden (AUT)Slalom Gigante Maschile
            2025-12-21 10:00 Alta Badia (ITA)Slalom Maschile
        e le converte in RaceEvent.
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        lines = text.splitlines()

        events: List[RaceEvent] = []

        for line in lines:
            line = line.strip()
            if not line or not line[0].isdigit():
                continue

            m = self.DATE_LINE_RE.match(line)
            if not m:
                continue

            date_str = m.group("date")
            time_str = m.group("time")
            rest = m.group("rest")

            # filtro stagione: teniamo solo date nell'anno stagione o stagione+1
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if d.year not in (season, season + 1):
                # calendario 25/26: con season=2025 teniamo 2025 e 2026
                continue

            # separa luogo + evento: "Soelden (AUT)Slalom Gigante Maschile"
            # → location = "Soelden (AUT)", event_name = "Slalom Gigante Maschile"
            loc, event_name = self._split_location_event(rest)

            # estrai nazione (ITA, AUT, ecc.)
            nation = self._extract_nation_from_location(loc)

            # mappa disciplina / livello
            disc = self._map_discipline(event_name)
            if discipline_filter and disc and disc != discipline_filter:
                continue

            level = "WC"
            category = "WC"

            # genere
            g = gender
            if "Maschile" in event_name:
                g = "M"
            elif "Femminile" in event_name:
                g = "F"

            # codice sintetico
            code = self._build_code(
                season=season,
                date_str=date_str,
                place=loc,
                gender=g,
                disc=disc,
            )

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc,
                code=code,
                name=event_name,
                nation=nation,
                region=None,
                place=loc,
                resort=None,
                start_date=d,
                end_date=d,
                category=category,
                level=level,
                gender=g,
                source_url=source_url,
            )
            events.append(ev)

        return events

    @staticmethod
    def _split_location_event(rest: str) -> tuple[str, str]:
        """
        Separa "Val Gardena / Groeden (ITA)Discesa Maschile"
        in:
            "Val Gardena / Groeden (ITA)", "Discesa Maschile"
        """
        rest = rest.strip()
        if ")" in rest:
            idx = rest.rfind(")")
            location = rest[: idx + 1].strip()
            event_name = rest[idx + 1 :].strip()
            if not event_name:
                event_name = location
            return location, event_name
        # fallback grezzo
        parts = rest.split(" ", 1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        return rest, rest

    @staticmethod
    def _extract_nation_from_location(location: str) -> Optional[str]:
        """
        "Alta Badia (ITA)" → "ITA"
        """
        m = re.search(r"\(([A-Z]{3})\)", location)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _map_discipline(event_name: str) -> Optional[str]:
        """
        Converte descrizione italiana in codice SL/GS/SG/DH.
        """
        up = event_name.upper()

        # attenzione all'ordine: prima GS, poi SL singolo
        if "GIGANTE" in up or "GS" in up:
            return Discipline.GS
        if "SLALOM" in up or "SL " in up or up.startswith("SL "):
            # esclude "SLALOM GIGANTE", già preso sopra
            if "GIGANTE" not in up:
                return Discipline.SL
        if "SUPER-G" in up or "SUPER G" in up or " SUPERG" in up or "SG " in up:
            return Discipline.SG
        if "DISCESA" in up or "DOWNHILL" in up:
            return Discipline.DH

        return None

    @staticmethod
    def _build_code(
        season: int,
        date_str: str,
        place: str,
        gender: Optional[str],
        disc: Optional[str],
    ) -> str:
        # NEVE-2025-10-26-SOELDEN-ITA-GS-M
        clean_place = (
            place.replace(" ", "_")
            .replace("/", "_")
            .replace("(", "")
            .replace(")", "")
        )
        parts = [
            "NEVE",
            str(season),
            date_str,
            clean_place,
        ]
        if disc:
            parts.append(disc)
        if gender:
            parts.append(gender)
        return "-".join(parts)


# ---------------------------------------------------------
# FISI — per ora NON DISPONIBILE via Neveitalia
# ---------------------------------------------------------

class FISICalendarProvider(BaseCalendarProvider):
    """
    Placeholder: Neveitalia NON espone un calendario strutturato FISI/comitati.
    Per ora ritorniamo lista vuota, in attesa di:
    - integrazione via FISI.org (quando risolto il 403/proxy), oppure
    - file offline (JSON/CSV) caricati a parte.
    """

    federation = Federation.FISI

    def __init__(
        self,
        http_client: Callable[[str, Optional[dict]], str],
        committee_slugs: Dict[str, str],
    ):
        self.http_client = http_client
        self.committee_slugs = committee_slugs

    def fetch_events(
        self,
        season,
        discipline=None,
        nation=None,
        region=None,
        category=None,
        level=None,
    ) -> List[RaceEvent]:
        # TODO: integrare FISI quando avremo una sorgente stabile.
        return []


# ---------------------------------------------------------
# SERVIZIO UNIFICATO
# ---------------------------------------------------------

class RaceCalendarService:
    def __init__(self, fis_provider: BaseCalendarProvider, fisi_provider: BaseCalendarProvider):
        self.fis = fis_provider
        self.fisi = fisi_provider

    def list_events(
        self,
        season: int,
        federation: Optional[str],
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:

        result: List[RaceEvent] = []

        if federation in (Federation.FIS, None):
            try:
                result += self.fis.fetch_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=None,
                )
            except Exception:
                # in produzione puoi loggare
                pass

        if federation in (Federation.FISI, None):
            try:
                result += self.fisi.fetch_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            except Exception:
                pass

        result.sort(key=lambda ev: ev.start_date)
        return result
