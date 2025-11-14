# core/race_events.py
# Calendari gare FIS/FISI — parsing Neveitalia per Coppa del Mondo

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, List, Optional
import re


HttpClient = Callable[[str, dict | None], str]


class Federation(Enum):
    FIS = "FIS"
    FISI = "FISI"


@dataclass
class RaceEvent:
    federation: Federation
    season: int
    discipline: Optional[str]  # "SL", "GS", "SG", "DH", ...
    gender: Optional[str]      # "M" / "F"
    nation: Optional[str]      # "AUT", "ITA", ...
    place: str                 # "Soelden (AUT)"
    name: str                  # "Slalom Gigante Maschile"
    start_date: datetime
    source_url: str


# -------------------------------------------------------------------
# Utilità parsing Neveitalia
# -------------------------------------------------------------------

_SPAN_TRIPLE_RE = re.compile(
    r'<span class="date">\s*([^<]+?)\s*</span>\s*'
    r'<span class="place">(?:<a [^>]*>)?([^<]+?)(?:</a>)?</span>\s*'
    r'<span class="event">\s*([^<]+?)\s*</span>',
    re.IGNORECASE | re.DOTALL,
)


def _parse_date(date_str: str) -> Optional[datetime]:
    s = date_str.strip()
    # es.: "2025-11-16 10:00" oppure "2025-10-26"
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H.%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _guess_discipline(event_name: str) -> Optional[str]:
    n = event_name.strip().lower()

    # ordine importante: "slalom gigante" prima di "slalom"
    if "slalom gigante" in n or "gigante" in n or "giant" in n:
        return "GS"
    if "slalom" in n:
        return "SL"
    if "super-g" in n or "super g" in n or "superg" in n:
        return "SG"
    if "discesa" in n or "downhill" in n:
        return "DH"

    return None


def _extract_nation(place: str) -> Optional[str]:
    # es.: "Soelden (AUT)" -> "AUT"
    m = re.search(r"\(([A-Z]{3})\)", place)
    if not m:
        return None
    return m.group(1)


# -------------------------------------------------------------------
# Provider FIS via Neveitalia
# -------------------------------------------------------------------

class FISCalendarProvider:
    """Calendario Coppa del Mondo via pagine Neveitalia (maschile + femminile)."""

    MEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario"
    WOMEN_URL = (
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"
    )

    def __init__(self, http_client: HttpClient):
        self.http_client = http_client

    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
    ) -> List[RaceEvent]:
        # scarico le due pagine; se quella femminile fallisce, ignoro l'errore
        html_m = self.http_client(self.MEN_URL, params=None)
        events: List[RaceEvent] = []
        events.extend(
            self._parse_neveitalia_page(
                html=html_m,
                season=season,
                gender="M",
                url=self.MEN_URL,
            )
        )

        try:
            html_f = self.http_client(self.WOMEN_URL, params=None)
        except Exception:
            html_f = ""
        if html_f:
            events.extend(
                self._parse_neveitalia_page(
                    html=html_f,
                    season=season,
                    gender="F",
                    url=self.WOMEN_URL,
                )
            )

        # filtri opzionali
        disc_up = discipline.upper() if discipline else None
        nat_up = nation.upper() if nation else None

        filtered: List[RaceEvent] = []
        for ev in events:
            if disc_up and (ev.discipline or "").upper() != disc_up:
                continue
            if nat_up and (ev.nation or "").upper() != nat_up:
                continue
            filtered.append(ev)

        filtered.sort(key=lambda e: e.start_date)
        return filtered

    def _parse_neveitalia_page(
        self,
        html: str,
        season: int,
        gender: str,
        url: str,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        for date_str, place, event_name in _SPAN_TRIPLE_RE.findall(html):
            dt = _parse_date(date_str)
            if dt is None:
                continue

            # stagione = anno di inizio (es. 2025 -> 2025/26)
            if dt.year not in (season, season + 1):
                continue

            disc = _guess_discipline(event_name)
            nat = _extract_nation(place)

            events.append(
                RaceEvent(
                    federation=Federation.FIS,
                    season=season,
                    discipline=disc,
                    gender=gender,
                    nation=nat,
                    place=place.strip(),
                    name=event_name.strip(),
                    start_date=dt,
                    source_url=url,
                )
            )

        return events


# -------------------------------------------------------------------
# Provider FISI (per ora stub, in attesa sorgente ufficiale)
# -------------------------------------------------------------------

class FISICalendarProvider:
    """Placeholder per futuro calendario FISI.

    Per ora ritorna sempre lista vuota: la logica è già pronta
    così, quando avremo una sorgente stabile, basterà implementare
    il parsing qui senza toccare la UI.
    """

    def __init__(self, http_client: HttpClient, committee_slugs: dict[str, str]):
        self.http_client = http_client
        self.committee_slugs = committee_slugs or {}

    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        # TODO: implementare quando avremo una sorgente FISI affidabile
        return []


# -------------------------------------------------------------------
# Servizio di alto livello per la UI
# -------------------------------------------------------------------

class RaceCalendarService:
    def __init__(
        self,
        fis_provider: FISCalendarProvider,
        fisi_provider: FISICalendarProvider,
    ):
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

        if federation is None or federation == Federation.FIS:
            events.extend(
                self.fis_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                )
            )

        if federation is None or federation == Federation.FISI:
            events.extend(
                self.fisi_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            )

        events.sort(key=lambda e: e.start_date)
        return events
