# core/race_events.py
# Telemark · Pro Wax & Tune
#
# Providers:
# - FIS: scraping NeveItalia (uomini + donne) con HTMLParser sui blocchi .ac-q
# - ASIVA: calendario Valle d’Aosta codificato a mano (estratto),
#          con filtri per mese e categoria (Partec.)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from html.parser import HTMLParser
from typing import Callable, List, Optional, Dict, Tuple
import re

import requests

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
# ENUM & MODEL
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
    category: Optional[str] = None  # Partec (A_M, U1_F, ecc.)
    raw_type: Optional[str] = None  # Tipo (FIS_NJR, PM_REG, …)
    level: Optional[str] = None     # WC, REG, ecc.

    @property
    def is_future(self) -> bool:
        return self.start_date >= date.today()


# ---------------------------------------------------------------------------
# DATE & DISCIPLINE HELPERS
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
    Parsing base per formati italiani (es. '9 dic 2025').
    Qui non ci serve coprire tutti i casi strani: NeveItalia usa ISO
    e ASIVA usa '9 dic 2025' → li normalizziamo qui sotto quando serve.
    """
    if not raw:
        return None
    s = raw.strip().lower()

    # ISO "2025-10-26" → usato da NeveItalia (lo gestiamo altrove con strptime)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None

    parts = s.split()
    if len(parts) != 3:
        return None

    try:
        day = int(parts[0])
        month = _MONTHS_IT.get(parts[1])
        year = int(parts[2])
        if not month:
            return None
        return date(year, month, day)
    except Exception:
        return None


def _map_discipline_code(text: str) -> Discipline:
    """Mappa descrizione evento → Discipline enum."""
    t = (text or "").lower()

    if "super-g" in t or "super g" in t:
        return Discipline.SG
    if "discesa" in t:
        return Discipline.DH
    if "gigante" in t or "gs " in t:
        return Discipline.GS
    if "slalom" in t or " sl " in t:
        return Discipline.SL

    # fallback ragionevole
    return Discipline.GS


# ---------------------------------------------------------------------------
# FIS PROVIDER — NEVEITALIA (HTMLParser su blocchi .ac-q)
# ---------------------------------------------------------------------------

# tipo per HTTP client iniettabile (utile per test)
HttpClient = Callable[[str, Optional[dict]], str]


class _NeveitaliaCalendarParser(HTMLParser):
    """
    Estrae (date_txt, place_txt, event_txt) dai blocchi:

    <div class="ac-q">
      <span class="date">2025-10-26 10:00</span>
      <span class="place">Soelden (AUT)</span>
      <span class="event">Slalom Gigante Maschile</span>
    </div>
    """

    def __init__(self) -> None:
        super().__init__()
        self.in_ac_q: bool = False
        self.current_span_class: Optional[str] = None
        self.buf_date: str = ""
        self.buf_place: str = ""
        self.buf_event: str = ""
        self.events_raw: List[tuple[str, str, str]] = []

    # ---- tag handling ----

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        if tag == "div":
            cls = attrs_dict.get("class", "")
            # le classi possono essere più di una, separiamo su spazio
            if "ac-q" in cls.split():
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

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.in_ac_q:
            date_txt = self.buf_date.strip()
            place_txt = self.buf_place.strip()
            event_txt = self.buf_event.strip()
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


class FISCalendarProvider:
    """
    Scarica il calendario di Coppa del Mondo da NeveItalia (M + F).

    - Maschile:  https://www.neveitalia.it/sport/scialpino/calendario
    - Femminile: https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile
    """

    MEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario"
    WOMEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"

    def __init__(self, http_client: Optional[HttpClient] = None) -> None:
        self.http_client: HttpClient = http_client or self._default_http_client

    # ---------- HTTP di default ----------

    @staticmethod
    def _default_http_client(url: str, params: Optional[dict] = None) -> str:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.text

    # ---------- API legacy: fetch_events (usata da list_events) ----------

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
            disc_enum = _map_discipline_code(event_txt)
            if discipline and disc_enum.value != discipline:
                continue

            # nazione: parte tra parentesi nel place, es. "Soelden (AUT)"
            m = re.search(r"\(([A-Z]{3})\)", place_txt)
            nation_code = m.group(1) if m else None
            if nation and nation_code and nation_code != nation:
                continue

            events.append(
                RaceEvent(
                    federation=Federation.FIS,
                    codex=None,
                    name=event_txt.strip(),
                    place=place_txt.strip(),
                    discipline=disc_enum,
                    start_date=d,
                    end_date=d,
                    nation=nation_code,
                    region=None,
                    category=None,
                    raw_type="FIS",
                    level="WC",
                )
            )

        return events

    # ---------- nuova API usata da RaceCalendarService ----------

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
        month: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[RaceEvent]:
        # month/category/region non disponibili su NeveItalia → ignorati per ora
        return self.fetch_events(
            season=season,
            discipline=discipline_filter,
            nation=nation_filter,
        )


# ---------------------------------------------------------------------------
# ASIVA PROVIDER — DATI CODIFICATI
# ---------------------------------------------------------------------------

# struttura compattata:
# codex, data_str, tipo, spec, category (Partec.), place, name
_ASIVA_RAW_EVENTS: List[Tuple[str, str, str, str, str, str, str]] = [
    # ---------------- DECEMBRE 2025 ----------------
    ("ITA5827", "9 dic 2025", "FIS_NJR", "GS", "F", "Courmayeur", "Trofeo ODL"),
    ("ITA0857", "9 dic 2025", "FIS_NJR", "GS", "M", "Courmayeur", "Trofeo ODL"),
    ("ITA5829", "10 dic 2025", "FIS_NJR", "GS", "F", "Courmayeur", "Trofeo ODL"),
    ("ITA0859", "10 dic 2025", "FIS_NJR", "GS", "M", "Courmayeur", "Trofeo ODL"),

    ("AA0001", "16 dic 2025", "PM_REG", "GS", "A_M", "Pila - Gressan", "Top 50"),
    ("AA0002", "16 dic 2025", "PM_REG", "GS", "A_F", "Pila - Gressan", "Top 50"),
    ("AA0003", "16 dic 2025", "PM_REG", "SL", "R_M", "Pila - Gressan", "Top 50"),
    ("AA0004", "16 dic 2025", "PM_REG", "SL", "R_F", "Pila - Gressan", "Top 50"),
    ("AA0005", "17 dic 2025", "PM_REG", "SL", "A_M", "Pila - Gressan", "Top 50"),
    ("AA0006", "17 dic 2025", "PM_REG", "SL", "A_F", "Pila - Gressan", "Top 50"),
    ("AA0007", "17 dic 2025", "PM_REG", "GS", "R_M", "Pila - Gressan", "Top 50"),
    ("AA0008", "17 dic 2025", "PM_REG", "GS", "R_F", "Pila - Gressan", "Top 50"),

    ("XA0184", "19 dic 2025", "PM_NAZ", "GS", "R_M", "Pila - Gressan", "Trofeo Coni"),
    ("XA0185", "19 dic 2025", "PM_NAZ", "GS", "R_F", "Pila - Gressan", "Trofeo Coni"),
    ("XA0186", "20 dic 2025", "PM_NAZ", "SL", "R_M", "Pila - Gressan", "Trofeo Coni"),
    ("XA0187", "20 dic 2025", "PM_NAZ", "SL", "R_F", "Pila - Gressan", "Trofeo Coni"),

    ("ITA5851", "20 dic 2025", "FIS_NJR", "SL", "F", "La Thuile", "Memorial Menel"),
    ("ITA0883", "20 dic 2025", "FIS_NJR", "SL", "M", "La Thuile", "Memorial Menel"),
    ("ITA5855", "21 dic 2025", "FIS_NJR", "SL", "F", "La Thuile", "Memorial Menel"),
    ("ITA0887", "21 dic 2025", "FIS_NJR", "SL", "M", "La Thuile", "Memorial Menel"),

    ("AA0011", "22 dic 2025", "RI_CHI_C", "SL", "A_M", "La Thuile", "Memorial Edoardo Camardella"),
    ("AA0012", "22 dic 2025", "RI_CHI_C", "SL", "A_F", "La Thuile", "Memorial Edoardo Camardella"),

    ("ITA5858", "22 dic 2025", "FIS", "GS", "F", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA0890", "22 dic 2025", "FIS", "GS", "M", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA5862", "23 dic 2025", "FIS", "GS", "F", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA0894", "23 dic 2025", "FIS", "GS", "M", "Frachey - Ayas", "Trofeo Pulverit"),

    ("AA0009", "21 dic 2025", "CHI_FL", "SL (3 manche)", "A_M", "Valtournenche",
     "Trofeo Igor Gorgonzola Flipper"),
    ("AA0010", "21 dic 2025", "CHI_FL", "SL (3 manche)", "A_F", "Valtournenche",
     "Trofeo Igor Gorgonzola Flipper"),

    ("AA0015", "23 dic 2025", "G_MAS GSG", "GS", "GSM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0020", "23 dic 2025", "G_MAS GSG", "GS", "GSM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0017", "23 dic 2025", "G_MAS GSG", "GS", "MAM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0022", "23 dic 2025", "G_MAS GSG", "GS", "MAM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0018", "23 dic 2025", "G_MAS GSG", "GS", "MBM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0023", "23 dic 2025", "G_MAS GSG", "GS", "MBM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0016", "23 dic 2025", "G_MAS GSG", "GS", "GSF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0021", "23 dic 2025", "G_MAS GSG", "GS", "GSF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0019", "23 dic 2025", "G_MAS GSG", "GS", "MCF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0024", "23 dic 2025", "G_MAS GSG", "GS", "MCF", "Torgnon", "Trofeo Sci Club Torgnon"),

    # ---------------- GENNAIO 2026 (estratto) ----------------
    ("AA0033", "10 gen 2026", "PUL_FL", "SL (3 manche)", "P1_M", "Frachey - Ayas", "Trofeo Casadei Flipper"),
    ("AA0034", "10 gen 2026", "PUL_FL", "SL (3 manche)", "P1_F", "Frachey - Ayas", "Trofeo Casadei Flipper"),
    ("AA0035", "11 gen 2026", "PUL_FL", "SL (3 manche)", "P2_M", "Frachey - Ayas", "Trofeo Casadei Flipper"),
    ("AA0036", "11 gen 2026", "PUL_FL", "SL (3 manche)", "P2_F", "Frachey - Ayas", "Trofeo Casadei Flipper"),

    ("ITA5879", "10 gen 2026", "FIS_NJR", "GS", "F", "Pila - Gressan", "Trofeo Asto"),
    ("ITA0911", "10 gen 2026", "FIS_NJR", "GS", "M", "Pila - Gressan", "Trofeo Asto"),
    ("ITA5883", "11 gen 2026", "FIS_NJR", "GS", "F", "Pila - Gressan", "Trofeo Asto"),
    ("ITA0915", "11 gen 2026", "FIS_NJR", "GS", "M", "Pila - Gressan", "Trofeo Asto"),

    # Gressoney - La Trinité
    ("AA0031", "10 gen 2026", "RQ_CHI", "SL", "A_M", "Gressoney - La - Trinité", "Trofeo Bergland"),
    ("AA0032", "10 gen 2026", "RQ_CHI", "SL", "A_F", "Gressoney - La - Trinité", "Trofeo Bergland"),
    ("AA0037", "11 gen 2026", "RQ_CHI", "GS", "A_M", "Gressoney - La - Trinité", "Trofeo Poggi"),
    ("AA0038", "11 gen 2026", "RQ_CHI", "GS", "A_F", "Gressoney - La - Trinité", "Trofeo Poggi"),

    # Crevacol (master GS, 17 gen)
    ("AA0041", "17 gen 2026", "G_MAS GSG", "GS", "GSM", "Crevacol", "Trofeo Mima"),
    ("AA0046", "17 gen 2026", "G_MAS GSG", "GS", "GSM", "Crevacol", "Trofeo Mima"),
    ("AA0043", "17 gen 2026", "G_MAS GSG", "GS", "MAM", "Crevacol", "Trofeo Mima"),
    ("AA0048", "17 gen 2026", "G_MAS GSG", "GS", "MAM", "Crevacol", "Trofeo Mima"),
    ("AA0044", "17 gen 2026", "G_MAS GSG", "GS", "MBM", "Crevacol", "Trofeo Mima"),
    ("AA0049", "17 gen 2026", "G_MAS GSG", "GS", "MBM", "Crevacol", "Trofeo Mima"),
    ("AA0042", "17 gen 2026", "G_MAS GSG", "GS", "GSF", "Crevacol", "Trofeo Mima"),
    ("AA0047", "17 gen 2026", "G_MAS GSG", "GS", "GSF", "Crevacol", "Trofeo Mima"),
    ("AA0045", "17 gen 2026", "G_MAS GSG", "GS", "MCF", "Crevacol", "Trofeo Mima"),
    ("AA0050", "17 gen 2026", "G_MAS GSG", "GS", "MCF", "Crevacol", "Trofeo Mima"),

    # ---------------- FEBBRAIO 2026 (estratto) ----------------
    ("AA0089", "8 feb 2026", "PI_PUL", "GS", "U1_M", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),
    ("AA0090", "8 feb 2026", "PI_PUL", "GS", "U1_F", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),
    ("AA0091", "8 feb 2026", "CR_PUL", "GS", "U2_M", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),
    ("AA0092", "8 feb 2026", "CR_PUL", "GS", "U2_F", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),

    ("ITA5942", "2 feb 2026", "FIS", "GS", "F", "Gressoney - Saint - Jean",
     "Coppa Comune di Gressoney Saint Jean"),
    ("ITA0974", "2 feb 2026", "FIS", "GS", "M", "Gressoney - Saint - Jean",
     "Coppa Comune di Gressoney Saint Jean"),

    ("ITA5953", "5 feb 2026", "FIS", "SL", "F", "Valgrisenche", "Trofeo MP Filtri"),
    ("ITA0985", "5 feb 2026", "FIS", "SL", "M", "Valgrisenche", "Trofeo MP Filtri"),

    # Pila – esempi misti febbraio
    ("AA0155", "28 feb 2026", "PUL_GG", "GS (2 manche)", "P1_M", "Pila - Gressan",
     "Coppa Comune di Gressan Gran Gigante"),
    ("AA0156", "28 feb 2026", "PUL_GG", "GS (2 manche)", "P1_F", "Pila - Gressan",
     "Coppa Comune di Gressan Gran Gigante"),

    # ---------------- MARZO 2026 (estratto) ----------------
    ("AA0203", "14 mar 2026", "PUL_GG", "GS (2 manche)", "U1_M", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),
    ("AA0204", "14 mar 2026", "PUL_GG", "GS (2 manche)", "U1_F", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),
    ("AA0205", "15 mar 2026", "PUL_GG", "GS (2 manche)", "U2_M", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),
    ("AA0206", "15 mar 2026", "PUL_GG", "GS (2 manche)", "U2_F", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),

    ("AA0185", "8 mar 2026", "PM_REG", "GS", "A_M", "Breuil Cervinia",
     "Trofeo Azzurri del Cervino"),
    ("AA0186", "8 mar 2026", "PM_REG", "GS", "A_F", "Breuil Cervinia",
     "Trofeo Azzurri del Cervino"),

    # Pila – Caldarelli Assicurazioni (master)
    ("AA0175", "8 mar 2026", "G_MAS GSG", "GS", "GSM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0180", "8 mar 2026", "G_MAS GSG", "GS", "GSM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0177", "8 mar 2026", "G_MAS GSG", "GS", "MAM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0182", "8 mar 2026", "G_MAS GSG", "GS", "MAM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0178", "8 mar 2026", "G_MAS GSG", "GS", "MBM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0183", "8 mar 2026", "G_MAS GSG", "GS", "MBM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0176", "8 mar 2026", "G_MAS GSG", "GS", "GSF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0181", "8 mar 2026", "G_MAS GSG", "GS", "GSF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0179", "8 mar 2026", "G_MAS GSG", "GS", "MCF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0184", "8 mar 2026", "G_MAS GSG", "GS", "MCF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),

    # ---------------- APRILE 2026 (estratto – Campionati ITA + Valtournenche) ----------------
    ("XA0148", "8 apr 2026", "CI_ALL", "GS", "A_M", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0149", "8 apr 2026", "CI_ALL", "GS", "A_F", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0150", "8 apr 2026", "CI_RAG", "SL", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0151", "8 apr 2026", "CI_RAG", "SL", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi"),

    ("XA0160", "12 apr 2026", "CI_ALL", "SL", "A_M", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0161", "12 apr 2026", "CI_ALL", "SL", "A_F", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0162", "12 apr 2026", "CI_RAG", "SX", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0163", "12 apr 2026", "CI_RAG", "SX", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi"),

    ("AA0243", "11 apr 2026", "PI_PUL", "GS", "P1_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0244", "11 apr 2026", "PI_PUL", "GS", "P1_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0245", "11 apr 2026", "PI_PUL", "GS", "P2_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0246", "11 apr 2026", "PI_PUL", "GS", "P2_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),

    ("AA0247", "12 apr 2026", "PM_PRO", "GS", "U1_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0248", "12 apr 2026", "PM_PRO", "GS", "U1_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0249", "12 apr 2026", "PI_PUL", "GS", "U2_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0250", "12 apr 2026", "PI_PUL", "GS", "U2_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),

    ("ITA6087", "15 apr 2026", "FIS", "SL", "F", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA1117", "15 apr 2026", "FIS", "SL", "M", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA6088", "16 apr 2026", "FIS", "SL", "F", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA1118", "16 apr 2026", "FIS", "SL", "M", "Valtournenche", "Trofeo Comune di Valtournenche"),

    ("ITA6089", "17 apr 2026", "FIS", "GS", "F", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("ITA1119", "17 apr 2026", "FIS", "GS", "M", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("ITA6090", "18 apr 2026", "FIS", "GS", "F", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("ITA1120", "18 apr 2026", "FIS", "GS", "M", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
]

# set di categorie ASIVA (Partec) per il menu a tendina
ASIVA_PARTEC_CODES: List[str] = sorted(
    {cat for (_, _, _, _, cat, _, _) in _ASIVA_RAW_EVENTS if cat and cat.strip()}
)


class ASIVACalendarProvider:
    """Calendario ASIVA codificato a mano, con filtri per mese e categoria."""

    def __init__(self) -> None:
        self._cache: Dict[int, List[RaceEvent]] = {}

    def _build_for_season(self, season: int) -> List[RaceEvent]:
        if season in self._cache:
            return self._cache[season]

        events: List[RaceEvent] = []

        for codex, date_raw, tipo, spec, category, place, name in _ASIVA_RAW_EVENTS:
            dt = _parse_date_it(date_raw)
            if not dt:
                continue

            # stagione tipo 2025–26: includo dicembre 2025 + gennaio–aprile 2026
            if dt.year not in (season, season + 1):
                continue

            ev = RaceEvent(
                federation=Federation.ASIVA,
                codex=None if codex == "N.D." else codex,
                name=name,
                place=place,
                discipline=_map_discipline_code(spec),
                start_date=dt,
                end_date=dt,
                nation="ITA",
                region="Valle d'Aosta",
                category=category,
                raw_type=tipo,
                level="REG",
            )
            events.append(ev)

        events.sort(key=lambda e: (e.start_date, e.place, e.name))
        self._cache[season] = events
        return events

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
        month: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[RaceEvent]:
        events = self._build_for_season(season)

        if discipline_filter:
            code = discipline_filter.upper()
            events = [
                ev
                for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        if month is not None:
            events = [ev for ev in events if ev.start_date.month == month]

        if category:
            cat = category.upper()
            events = [
                ev
                for ev in events
                if ev.category and ev.category.upper() == cat
            ]

        if nation_filter:
            nf = nation_filter.upper()
            events = [
                ev
                for ev in events
                if (ev.nation or "").upper() == nf
            ]

        if region_filter:
            rf = region_filter.lower()
            events = [
                ev
                for ev in events
                if (ev.region or "").lower() == rf
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
        month: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        if federation is None or federation == Federation.FIS:
            try:
                events.extend(
                    self._fis.list_events(
                        season=season,
                        discipline_filter=discipline,
                        nation_filter=nation,
                        region_filter=region,
                        month=month,
                        category=category,
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
                        nation_filter=nation,
                        region_filter=region,
                        month=month,
                        category=category,
                    )
                )
            except Exception:
                pass

        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
