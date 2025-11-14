# core/race_events.py
# Calendari gare (FIS / FISI) per Telemark · Pro Wax & Tune

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import re
from typing import Callable, Iterable, List, Optional


# ============================================================
# MODELLI DI BASE
# ============================================================

class Federation(enum.Enum):
    FIS = "FIS"
    FISI = "FISI"


@dataclasses.dataclass
class RaceEvent:
    federation: Federation
    name: str
    discipline: Optional[str]  # "SL", "GS", "SG", "DH", ecc
    place: str                 # es. "Soelden (AUT)"
    nation: Optional[str]      # es. "AUT"
    level: str                 # es. "WC"
    start_date: dt.date
    end_date: dt.date
    source_url: str
    raw_label: str             # testo grezzo evento
    extra: dict                # campo libero


# tipo di funzione HTTP esterna
HttpClient = Callable[[str, Optional[dict]], str]


# ============================================================
# PROVIDER BASE
# ============================================================

class BaseCalendarProvider:
    def list_events(
        self,
        season: int,
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:
        raise NotImplementedError


# ============================================================
# FIS via NEVEITALIA
# ============================================================

_DISCIPLINE_MAP = {
    "slalom maschile": "SL",
    "slalom femminile": "SL",
    "slalom gigante maschile": "GS",
    "slalom gigante femminile": "GS",
    "super-g maschile": "SG",
    "super-g femminile": "SG",
    "discesa maschile": "DH",
    "discesa femminile": "DH",
}


def _parse_neveitalia_calendar_html(
    html: str,
    base_url: str,
    season: int,
    gender: str,
) -> List[RaceEvent]:
    """
    Parser minimale per il calendario Neveitalia (pagina Coppa del Mondo).
    Si appoggia sulla struttura dei blocchi <div class="ac js-enabled">.
    """

    # Prendiamo solo il blocco principale con la classe "accordion-container"
    m_container = re.search(
        r'<div class="accordion-container".*?>(.*?)</div>\s*</div>\s*</div>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not m_container:
        return []

    container = m_container.group(1)

    events: List[RaceEvent] = []

    # Ogni evento è un div.ac con dentro 3 span: date, place, event
    ac_blocks = re.findall(
        r'<div class="ac js-enabled".*?>(.*?)</div>\s*</div>\s*',
        container,
        flags=re.DOTALL | re.IGNORECASE,
    )

    for block in ac_blocks:
        # Data
        m_date = re.search(
            r'<span class="date">\s*([^<]+?)\s*</span>',
            block,
            flags=re.IGNORECASE,
        )
        if not m_date:
            continue
        raw_date = m_date.group(1).strip()

        # alcune date hanno orario, altre no → normalizziamo
        # es. "2025-10-26" oppure "2025-11-16 10:00"
        if " " in raw_date:
            # ignoriamo l'ora, ci basta la parte di data
            raw_date_part = raw_date.split()[0]
        else:
            raw_date_part = raw_date

        try:
            start_date = dt.date.fromisoformat(raw_date_part)
        except Exception:
            # formato sconosciuto, saltiamo
            continue

        # teniamo solo gare della coppia season / season+1
        if start_date.year not in (season, season + 1):
            continue

        # Place (può contenere un <a>)
        m_place = re.search(
            r'<span class="place">(?:\s*<a[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*</span>',
            block,
            flags=re.IGNORECASE,
        )
        place = m_place.group(1).strip() if m_place else ""

        # Evento / descrizione
        m_event = re.search(
            r'<span class="event">\s*([^<]+?)\s*</span>',
            block,
            flags=re.IGNORECASE,
        )
        raw_label = m_event.group(1).strip() if m_event else ""

        label_lower = raw_label.lower()

        # Disciplina FIS
        discipline: Optional[str] = None
        for key, code in _DISCIPLINE_MAP.items():
            if key in label_lower:
                discipline = code
                break

        # nazione da parentesi finali nel place: "Soelden (AUT)"
        nation: Optional[str] = None
        m_nat = re.search(r"\(([A-Z]{3})\)\s*$", place)
        if m_nat:
            nation = m_nat.group(1)

        ev = RaceEvent(
            federation=Federation.FIS,
            name=raw_label.strip(),
            discipline=discipline,
            place=place,
            nation=nation,
            level="WC",
            start_date=start_date,
            end_date=start_date,  # la pagina non espone data fine, per ora uguale
            source_url=base_url,
            raw_label=raw_label,
            extra={
                "gender": gender,
            },
        )
        events.append(ev)

    return events


class FISCalendarProvider(BaseCalendarProvider):
    """
    Provider che usa le pagine calendario di Neveitalia per la Coppa del Mondo.
    Attualmente:
      - maschile:  https://www.neveitalia.it/sport/scialpino/calendario
      - femminile: https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile
    """

    MEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario"
    WOMEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"

    def __init__(self, http_client: HttpClient):
        self._http = http_client

    def list_events(
        self,
        season: int,
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:
        # scarichiamo entrambi i calendari (maschile + femminile)
        html_m = self._http(self.MEN_URL, params=None)
        html_f = self._http(self.WOMEN_URL, params=None)

        events_m = _parse_neveitalia_calendar_html(
            html_m, base_url=self.MEN_URL, season=season, gender="M"
        )
        events_f = _parse_neveitalia_calendar_html(
            html_f, base_url=self.WOMEN_URL, season=season, gender="F"
        )

        all_events = events_m + events_f

        # filtri lato codice
        def _match(ev: RaceEvent) -> bool:
            if discipline and ev.discipline and ev.discipline != discipline:
                return False
            if discipline and ev.discipline is None:
                # se filtro per disciplina, scartiamo eventi non riconosciuti
                return False
            if nation and ev.nation and ev.nation != nation:
                return False
            return True

        filtered = [ev for ev in all_events if _match(ev)]

        # ordiniamo per data
        filtered.sort(key=lambda ev: (ev.start_date, ev.place, ev.name))
        return filtered


# ============================================================
# FISI (stub per il futuro)
# ============================================================

class FISICalendarProvider(BaseCalendarProvider):
    """
    Per ora è uno stub: ritorna lista vuota.
    Parametro committee_slugs è tenuto solo per compatibilità futura.
    """

    def __init__(self, http_client: HttpClient, committee_slugs: dict[str, str]):
        self._http = http_client
        self._committee_slugs = committee_slugs

    def list_events(
        self,
        season: int,
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:
        # TODO: implementare quando troveremo una sorgente FISI stabile
        return []


# ============================================================
# AGGREGATORE
# ============================================================

class RaceCalendarService:
    """
    Service che aggrega diversi provider (FIS, FISI, ecc.)
    """

    def __init__(
        self,
        fis_provider: Optional[FISCalendarProvider] = None,
        fisi_provider: Optional[FISICalendarProvider] = None,
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
        providers: List[tuple[Federation, BaseCalendarProvider]] = []

        if federation is None or federation is Federation.FIS:
            if self.fis_provider:
                providers.append((Federation.FIS, self.fis_provider))

        if federation is None or federation is Federation.FISI:
            if self.fisi_provider:
                providers.append((Federation.FISI, self.fisi_provider))

        events: List[RaceEvent] = []
        for fed, provider in providers:
            try:
                evs = provider.list_events(
                    season=season,
                    discipline=discipline,
                    nation=nation,
                    region=region,
                )
            except Exception:
                # non blocchiamo l'intero service se un provider va giù
                continue
            # assicuriamoci che la federation sia impostata correttamente
            for ev in evs:
                ev.federation = fed
            events.extend(evs)

        events.sort(key=lambda ev: (ev.start_date, ev.place, ev.name))
        return events
