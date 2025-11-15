# core/race_events.py
# ------------------------------------------------------------
# Lettura calendario Coppa del Mondo da Neveitalia
# (solo FIS World Cup, maschile per ora) + servizio di filtro
# ------------------------------------------------------------

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable, Iterable, List, Optional

import re


# ------------------------------------------------------------
# Modelli base
# ------------------------------------------------------------

class Federation(Enum):
    FIS = "FIS"
    FISI = "FISI"   # placeholder per futuro


class RaceDiscipline(str, Enum):
    SL = "SL"
    GS = "GS"
    SG = "SG"
    DH = "DH"
    OTHER = "OTHER"


@dataclass
class RaceEvent:
    start_date: date
    place: str
    name: str
    discipline: RaceDiscipline
    federation: Federation
    # string grezza utile per debug / logging
    raw_source: Optional[str] = None


HttpClient = Callable[[str, Optional[dict]], str]


# ------------------------------------------------------------
# Parser HTML Neveitalia (molto tollerante)
# ------------------------------------------------------------

# pattern che trova OGNI blocco <div class="ac-q">…</div>
_AC_Q_RE = re.compile(
    r'<div\s+class="ac-q"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)

# dentro al blocco cerchiamo gli span date/place/event
_SPAN_RE = re.compile(
    r'<span\s+class="(?P<cls>date|place|event)"[^>]*>(?P<val>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)

# data tipo 2025-11-16 o 2025-11-16 10:00
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _strip_tags(html: str) -> str:
    """Rimuove tutti i tag HTML e normalizza gli spazi."""
    txt = re.sub(r"<[^>]+>", " ", html)
    return " ".join(txt.split())


def _map_discipline(event_label: str) -> RaceDiscipline:
    """Mappa il testo 'Slalom Gigante Maschile' → RaceDiscipline.GS, ecc."""
    s = event_label.lower()

    # ordine importante: prima "gigante", poi "slalom"
    if "gigante" in s:
        return RaceDiscipline.GS
    if "slalom" in s:
        return RaceDiscipline.SL
    if "super-g" in s or "super g" in s:
        return RaceDiscipline.SG
    if "discesa" in s:
        return RaceDiscipline.DH
    return RaceDiscipline.OTHER


def _parse_neveitalia_html(
    html: str,
    season: int,
    discipline: Optional[str] = None,
) -> List[RaceEvent]:
    """
    Parsea la pagina calendario di Neveitalia e restituisce gli eventi.

    season = anno di inizio (es. 2025 per stagione 2025/26)
    discipline = None oppure "SL"/"GS"/"SG"/"DH"
    """

    events: List[RaceEvent] = []

    for m in _AC_Q_RE.finditer(html):
        block = m.group(1)

        fields = {"date": "", "place": "", "event": ""}

        for sm in _SPAN_RE.finditer(block):
            cls = sm.group("cls").lower()
            val = _strip_tags(sm.group("val"))
            fields[cls] = val

        date_str = fields["date"]
        place = fields["place"]
        name = fields["event"]

        # Se manca qualcosa, saltiamo
        if not date_str or not place or not name:
            continue

        dm = _DATE_RE.search(date_str)
        if not dm:
            continue

        year, month, day = map(int, dm.groups())
        d = date(year, month, day)

        # stagione tipo 2025 → accetto anni 2025 o 2026
        if d.year not in (season, season + 1):
            continue

        disc = _map_discipline(name)

        # filtro disciplina se richiesto
        if discipline is not None:
            code = discipline.upper()
            if disc.value != code:
                continue

        ev = RaceEvent(
            start_date=d,
            place=place,
            name=name,
            discipline=disc,
            federation=Federation.FIS,
            raw_source=block.strip(),
        )
        events.append(ev)

    # ordiniamo per data
    events.sort(key=lambda e: e.start_date)
    return events


# ------------------------------------------------------------
# Provider Neveitalia FIS
# ------------------------------------------------------------

class FISCalendarProvider:
    """
    Provider che legge il calendario di Coppa del Mondo da Neveitalia.

    Per ora: maschile, URL fisso /sport/scialpino/calendario
    (sul markup che mi hai incollato).
    """

    def __init__(
        self,
        http_client: HttpClient,
        base_url: Optional[str] = None,
    ) -> None:
        self.http_client = http_client
        self.base_url = (
            base_url
            or "https://www.neveitalia.it/sport/scialpino/calendario"
        )

    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,   # ignorati ma tenuti per compatibilità
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        html = self.http_client(self.base_url, params=None)
        return _parse_neveitalia_html(html, season=season, discipline=discipline)


# ------------------------------------------------------------
# Stub FISI (non attivo per ora)
# ------------------------------------------------------------

class FISICalendarProvider:
    """
    Placeholder per futuro calendario FISI.
    Al momento ritorna lista vuota.
    """

    def __init__(
        self,
        http_client: HttpClient,
        committee_slugs: Optional[dict[str, str]] = None,
    ) -> None:
        self.http_client = http_client
        self.committee_slugs = committee_slugs or {}

    def list_events(
        self,
        season: int,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        # da implementare quando avremo una sorgente FISI stabile
        return []


# ------------------------------------------------------------
# Servizio di alto livello: unifica FIS / FISI
# ------------------------------------------------------------

class RaceCalendarService:
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
        federation: Optional[Federation] = None,
        discipline: Optional[str] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
    ) -> List[RaceEvent]:
        """
        Restituisce la lista di eventi per la stagione / filtri richiesti.

        federation:
            - None → tutte le federazioni disponibili (per ora solo FIS)
            - Federation.FIS
            - Federation.FISI
        discipline:
            - None → tutte
            - "SL"/"GS"/"SG"/"DH"
        """
        events: List[RaceEvent] = []

        if federation in (None, Federation.FIS):
            events.extend(
                self.fis_provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            )

        if federation in (None, Federation.FISI) and self.fisi_provider is not None:
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
