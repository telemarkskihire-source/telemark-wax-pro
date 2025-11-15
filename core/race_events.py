# core/race_events.py
# Calendari gare FIS/FISI via Neveitalia (parser HTML nuovo, senza dipendenze esterne)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Callable, List, Optional
import re


# =====================================================================
# MODELLI DI DOMINIO
# =====================================================================

class Federation(Enum):
    FIS = "FIS"
    FISI = "FISI"


@dataclass
class RaceEvent:
    federation: Federation
    season: int               # anno di inizio (es. 2025 per 2025/26)
    start_date: date
    place: str                # es. "Soelden (AUT)"
    nation: Optional[str]     # es. "AUT"
    name: str                 # es. "Slalom Gigante Maschile"
    discipline: Optional[str] # "SL", "GS", "SG", "DH", ecc.
    raw_label: str            # testo originale del campo evento
    source_url: str           # URL Neveitalia


# =====================================================================
# UTILITY PARSING
# =====================================================================

SPAN_RE_TEMPLATE = r'<span class="{cls}">(.*?)</span>'


def _strip_tags(html: str) -> str:
    """Rimuove tutti i tag HTML e normalizza gli spazi."""
    text = re.sub(r"<[^>]+>", "", html)
    return " ".join(text.split())


def _extract_span(inner_html: str, cls: str) -> str:
    """Estrae il contenuto di <span class="cls">...</span>."""
    pattern = re.compile(SPAN_RE_TEMPLATE.format(cls=cls), re.DOTALL | re.IGNORECASE)
    m = pattern.search(inner_html)
    if not m:
        return ""
    return _strip_tags(m.group(1))


def _parse_date(text: str) -> Optional[date]:
    """Parsa '2025-11-16 10:00' oppure '2025-10-26' in oggetto date."""
    raw = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date()
        except ValueError:
            continue
    return None


def _map_discipline(label: str) -> Optional[str]:
    """Converte descrizione italiana in codice disciplina FIS."""
    t = label.lower()

    if "slalom gigante" in t:
        return "GS"
    if "slalom" in t:
        # deve andare dopo "slalom gigante"
        return "SL"
    if "super-g" in t or "super g" in t or "super g" in t.replace("-", " "):
        return "SG"
    if "discesa" in t:
        return "DH"
    # altre discipline (parallel, team, ecc.) al momento non mappate
    return None


def _extract_nation_from_place(place: str) -> Optional[str]:
    """
    Estrae la sigla nazione se è presente fra parentesi: 'Soelden (AUT)' → 'AUT'.
    """
    m = re.search(r"\(([A-Z]{3})\)", place)
    if m:
        return m.group(1)
    return None


# =====================================================================
# PROVIDER NEVEITALIA — FIS
# =====================================================================

HttpClient = Callable[[str, Optional[dict]], str]


class FISCalendarProvider:
    """
    Parser del calendario Coppa del Mondo (maschile per ora) da Neveitalia.

    URL base maschile:
      https://www.neveitalia.it/sport/scialpino/calendario

    Il calendario riportato è per la stagione corrente (25/26, 26/27, ...).
    Noi filtriamo gli eventi sul parametro `season` (anno di inizio).
    """

    BASE_URL_MEN = "https://www.neveitalia.it/sport/scialpino/calendario"
    # FUTURO: BASE_URL_WOMEN = ".../calendario/coppa-del-mondo-femminile"

    def __init__(self, http_client: HttpClient):
        self.http_client = http_client

    # --------------------------------------------------------------
    def fetch_html(self, season: int) -> str:
        """
        Per ora Neveitalia non usa un querystring per la stagione,
        quindi ignoriamo `season` e prendiamo sempre la pagina corrente.
        """
        return self.http_client(self.BASE_URL_MEN, params=None)

    # --------------------------------------------------------------
    def parse_html(
        self,
        html: str,
        season: int,
        discipline: Optional[str],
        nation: Optional[str],
    ) -> List[RaceEvent]:
        """
        Parser basato sulla struttura attuale:

        <div id="firstCard" class="main-drop-down-menu">
          <div class="accordion-container">
            <div class="ac">
              <div class="ac-q" ...>
                <span class="date">2025-10-26 </span>
                <span class="place"><a ...>Soelden (AUT)</a></span>
                <span class="event">Slalom Gigante Maschile </span>
              </div>
              ...
        """
        events: List[RaceEvent] = []

        # Prendiamo solo la parte del calendario per essere un po' più robusti
        m_container = re.search(
            r'<div class="accordion-container">(.*?)</div>\s*</div>\s*<!-- seasonPar',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        container = m_container.group(1) if m_container else html

        ac_q_pattern = re.compile(
            r'<div class="ac-q"[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )

        for m in ac_q_pattern.finditer(container):
            inner = m.group(1)

            raw_date = _extract_span(inner, "date")
            raw_place = _extract_span(inner, "place")
            raw_event = _extract_span(inner, "event")

            if not raw_date or not raw_place or not raw_event:
                continue

            d = _parse_date(raw_date)
            if not d:
                continue

            # Filtra per stagione: anno == season o season+1 (calendario 25/26)
            if d.year not in (season, season + 1):
                continue

            discipl_code = _map_discipline(raw_event)

            # Filtra per disciplina se richiesta (SL/GS/SG/DH)
            if discipline is not None and discipl_code != discipline:
                continue

            place = raw_place.strip()
            nat = _extract_nation_from_place(place)

            # Filtra per nazione se richiesto
            if nation is not None and nat != nation:
                continue

            ev = RaceEvent(
                federation=Federation.FIS,
                season=season,
                start_date=d,
                place=place,
                nation=nat,
                name=raw_event.strip(),
                discipline=discipl_code,
                raw_label=raw_event.strip(),
                source_url=self.BASE_URL_MEN,
            )
            events.append(ev)

        # Ordina cronologicamente
        events.sort(key=lambda e: e.start_date)
        return events

    # --------------------------------------------------------------
    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
    ) -> List[RaceEvent]:
        html = self.fetch_html(season)
        return self.parse_html(html, season=season, discipline=discipline, nation=nation)


# =====================================================================
# PROVIDER FISI — per ora disattivato
# =====================================================================

class FISICalendarProvider:
    """
    Placeholder: al momento NON usiamo una sorgente stabile FISI.
    Ritorna sempre lista vuota, ma mantiene la stessa interfaccia.
    """

    def __init__(self, http_client: HttpClient, committee_slugs: dict[str, str] | None = None):
        self.http_client = http_client
        self.committee_slugs = committee_slugs or {}

    def list_events(
        self,
        season: int,
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:
        # Quando avremo una sorgente FISI vera, implementeremo qui.
        return []


# =====================================================================
# SERVIZIO DI FUSIONE
# =====================================================================

class RaceCalendarService:
    """
    Facciata unica per ottenere eventi da FIS (Neveitalia) e FISI.
    """

    def __init__(
        self,
        fis_provider: FISCalendarProvider,
        fisi_provider: Optional[FISICalendarProvider] = None,
    ):
        self.fis_provider = fis_provider
        self.fisi_provider = fisi_provider

    # --------------------------------------------------------------
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
                self.fis_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                )
            )

        if federation in (Federation.FISI, None) and self.fisi_provider is not None:
            events.extend(
                self.fisi_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            )

        # Ordina tutte le gare fuse per data
        events.sort(key=lambda e: e.start_date)
        return events
