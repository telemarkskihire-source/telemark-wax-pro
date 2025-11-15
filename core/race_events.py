# core/race_events.py
# Calendari gare FIS/FISI – integrazione Neveitalia per Telemark · Pro Wax & Tune

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from html.parser import HTMLParser
from typing import Callable, List, Optional
import re

import requests


# ---------------------------------------------------------------------------
# Modelli di base
# ---------------------------------------------------------------------------

class Federation(Enum):
    FIS = "FIS"
    FISI = "FISI"


@dataclass
class RaceEvent:
    start_date: date
    place: str
    nation: Optional[str]
    name: str
    discipline: Optional[str]  # "SL", "GS", "SG", "DH", ecc.
    federation: Federation


# ---------------------------------------------------------------------------
# Parser HTML specifico Neveitalia
#   lavora sui blocchi:
#   <div class="ac">
#     <div class="ac-q">
#       <span class="date">2025-10-26 10:00 </span>
#       <span class="place">Soelden (AUT)</span>
#       <span class="event">Slalom Gigante Maschile </span>
# ---------------------------------------------------------------------------

class _NeveitaliaCalendarParser(HTMLParser):
    """Estrae (date, place, event) dai blocchi .ac-q del calendario."""

    def __init__(self) -> None:
        super().__init__()
        self.in_ac_q = False
        self.current_span_class: Optional[str] = None
        self.buf_date: str = ""
        self.buf_place: str = ""
        self.buf_event: str = ""
        self.events_raw: List[tuple[str, str, str]] = []

    # --------- tag handling ---------

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        if tag == "div":
            cls = attrs_dict.get("class", "")
            if "ac-q" in cls.split():
                # inizio nuovo evento
                self.in_ac_q = True
                self.current_span_class = None
                self.buf_date = ""
                self.buf_place = ""
                self.buf_event = ""
        elif self.in_ac_q and tag == "span":
            cls = attrs_dict.get("class", "")
            if "date" in cls:
                self.current_span_class = "date"
            elif "place" in cls:
                self.current_span_class = "place"
            elif "event" in cls:
                self.current_span_class = "event"
        # <a> dentro place: manteniamo current_span_class così com'è

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.in_ac_q:
            # chiusura del blocco .ac-q → salviamo l’evento
            date_txt = self.buf_date.strip()
            event_txt = self.buf_event.strip()
            place_txt = self.buf_place.strip()
            if date_txt and event_txt:
                self.events_raw.append((date_txt, place_txt, event_txt))
            self.in_ac_q = False
            self.current_span_class = None

    def handle_data(self, data: str) -> None:
        if not (self.in_ac_q and self.current_span_class):
            return
        if self.current_span_class == "date":
            self.buf_date += data
        elif self.current_span_class == "place":
            self.buf_place += data
        elif self.current_span_class == "event":
            self.buf_event += data


# ---------------------------------------------------------------------------
# Provider FIS via Neveitalia (maschile + femminile)
# ---------------------------------------------------------------------------

HttpClient = Callable[[str, Optional[dict]], str]


class FISCalendarProvider:
    """Scarica il calendario di Coppa del Mondo da Neveitalia (M + F)."""

    MEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario"
    WOMEN_URL = (
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"
    )

    def __init__(self, http_client: Optional[HttpClient] = None) -> None:
        self.http_client: HttpClient = http_client or self._default_http_client

    # ---------- HTTP di default ----------

    @staticmethod
    def _default_http_client(url: str, params: Optional[dict] = None) -> str:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.text

    # ---------- API esterna ----------

    def fetch_events(
        self,
        season: int,
        discipline: Optional[str] = None,  # "SL"/"GS"/"SG"/"DH" oppure None
        nation: Optional[str] = None,      # "ITA", "AUT", ecc. oppure None
    ) -> List[RaceEvent]:
        """Ritorna eventi FIS (uomo + donna) filtrati per stagione/disciplina/nazione."""
        html_pages: List[str] = []
        for url in (self.MEN_URL, self.WOMEN_URL):
            try:
                html_pages.append(self.http_client(url, None))
            except Exception:
                # se una delle due pagine fallisce continuiamo con l’altra
                continue

        all_events: List[RaceEvent] = []
        for html in html_pages:
            all_events.extend(
                self._parse_neveitalia_html(
                    html=html,
                    season=season,
                    discipline=discipline,
                    nation=nation,
                )
            )

        all_events.sort(key=lambda ev: ev.start_date)
        return all_events

    # ---------- parsing HTML ----------

    def _parse_neveitalia_html(
        self,
        html: str,
        season: int,
        discipline: Optional[str],
        nation: Optional[str],
    ) -> List[RaceEvent]:
        parser = _NeveitaliaCalendarParser()
        parser.feed(html)

        events: List[RaceEvent] = []

        for date_txt, place_txt, event_txt in parser.events_raw:
            # data: "2025-10-26 10:00" → prendiamo solo AAAA-MM-GG
            date_part = date_txt.strip().split()[0]
            try:
                d = datetime.strptime(date_part, "%Y-%m-%d").date()
            except ValueError:
                continue

            # stagione: anno == season oppure season+1 (es. 2025/2026)
            if d.year not in (season, season + 1):
                continue

            # disciplina: mappiamo dall’italiano al codice
            disc_code = self._map_discipline(event_txt)
            if discipline and disc_code != discipline:
                continue

            # nazione: parte tra parentesi nel place, es. "Soelden (AUT)"
            m = re.search(r"\(([A-Z]{3})\)", place_txt)
            nation_code = m.group(1) if m else None
            if nation and nation_code and nation_code != nation:
                continue

            events.append(
                RaceEvent(
                    start_date=d,
                    place=place_txt.strip(),
                    nation=nation_code,
                    name=event_txt.strip(),
                    discipline=disc_code,
                    federation=Federation.FIS,
                )
            )

        return events

    # ---------- mapping discipline ----------

    @staticmethod
    def _map_discipline(text: str) -> Optional[str]:
        t = text.lower()
        # l’ordine è importante: prima super-g, poi discesa, poi gigante, poi slalom
        if "super-g" in t or "super g" in t:
            return "SG"
        if "discesa" in t:
            return "DH"
        if "gigante" in t:
            return "GS"
        if "slalom" in t:
            return "SL"
        return None


# ---------------------------------------------------------------------------
# Provider FISI – per ora stub (ritorna lista vuota)
# ---------------------------------------------------------------------------

class FISICalendarProvider:
    """Placeholder per calendario FISI, per ora disattivato."""

    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        committee_slugs: Optional[dict[str, str]] = None,
    ) -> None:
        self.http_client: HttpClient = http_client or FISCalendarProvider._default_http_client
        self.committee_slugs = committee_slugs or {}

    def fetch_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        # TODO: implementare quando avremo una sorgente FISI affidabile
        return []


# ---------------------------------------------------------------------------
# Facade: RaceCalendarService
# ---------------------------------------------------------------------------

class RaceCalendarService:
    """Punto di accesso unico per Streamlit (FIS + FISI)."""

    def __init__(
        self,
        fis_provider: FISCalendarProvider,
        fisi_provider: Optional[FISICalendarProvider] = None,
    ) -> None:
        self.fis_provider = fis_provider
        self.fisi_provider = fisi_provider

    def list_events(
        self,
        season: int,
        federation: Optional[Federation],
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        if federation in (Federation.FIS, None):
            events.extend(
                self.fis_provider.fetch_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                )
            )

        if self.fisi_provider is not None and federation in (Federation.FISI, None):
            events.extend(
                self.fisi_provider.fetch_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            )

        events.sort(key=lambda ev: ev.start_date)
        return events
