# core/race_events.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional, Iterable, Dict, Callable

try:
    # se hai già messo Discipline in core.race_tuning
    from core.race_tuning import Discipline
except ImportError:
    # fallback minimo se vuoi testare il modulo da solo
    class Discipline(str, Enum):
        SL = "SL"
        GS = "GS"
        SG = "SG"
        DH = "DH"


class Federation(str, Enum):
    FIS = "FIS"
    FISI = "FISI"


@dataclass
class RaceEvent:
    """
    Evento di gara unificato per FIS / FISI (e in futuro altri).
    """
    federation: Federation
    season: int                  # es. 2025 per stagione 2025/26
    discipline: Optional[Discipline]

    # Identificativi
    code: str                    # FIS race codex, codice FISI, ecc.
    name: str                    # nome competizione (es. "Kaabdalis Magic Drum FIS")

    # Localizzazione
    nation: Optional[str]        # es. "ITA", "AUT", "SWE"
    region: Optional[str]        # per FISI: "VENETO", "VALLE D'AOSTA", ecc.
    place: str                   # città/località (es. "Champoluc")
    resort: Optional[str]        # impianto/pista (quando disponibile)

    # Timing
    start_date: date
    end_date: date

    # Meta gara
    category: Optional[str]      # GIOVANI, SENIOR, BABY, MASTER, ECC
    level: Optional[str]         # WC, EC, FIS, ENL, NJR, CIT, REG, PROV, ecc.
    gender: Optional[str]        # "M", "F", "MF"

    # Link sorgente
    source_url: Optional[str]    # URL pagina ufficiale FIS/FISI

    def is_in_range(self, start: Optional[date], end: Optional[date]) -> bool:
        if start and self.end_date < start:
            return False
        if end and self.start_date > end:
            return False
        return True


# -----------------------------
#   Provider astratti
# -----------------------------


class BaseCalendarProvider:
    """
    Interfaccia base per qualsiasi provider di calendario (FIS, FISI, ecc.).
    """

    federation: Federation

    def fetch_events(
        self,
        season: int,
        discipline: Optional[Discipline] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
        category: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[RaceEvent]:
        """
        Restituisce una lista di eventi per la stagione e i filtri dati.

        IMPLEMENTAZIONE SPECIFICA nei sotto-provider:
        - FISCalendarProvider → scraping/API dal sito FIS
        - FISICalendarProvider → scraping/API da fisi.org o comitati
        """
        raise NotImplementedError


# -----------------------------
#   Provider FIS (internazionale)
# -----------------------------


class FISCalendarProvider(BaseCalendarProvider):
    """
    Provider per i calendari FIS (tutti i livelli: WC, EC, FIS, ENL, ecc.)

    Riferimento web:
    - Calendario generale FIS: https://www.fis-ski.com/DB/general/calendar-results.html
    - Calendario Sci Alpino: https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html
    """

    federation = Federation.FIS

    BASE_URL = (
        "https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html"
    )

    def __init__(
        self,
        http_client: Optional[Callable[[str, dict], str]] = None,
    ) -> None:
        """
        http_client: callable opzionale per effettuare richieste.
        Firma attesa: (url: str, params: dict) -> str (HTML)
        Se None: in produzione puoi usare 'requests.get' incapsulato.
        """
        self.http_client = http_client

    def fetch_events(
        self,
        season: int,
        discipline: Optional[Discipline] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,  # non usato per FIS ma per compatibilità
        category: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[RaceEvent]:
        """
        TODO: implementare scraping reale del calendario FIS.

        Qui ti do la struttura dei filtri e un esempio di payload.
        In produzione:
        - costruisci la query string (es. seasoncode, nationcode, ecc.)
        - scarica HTML
        - fai il parse in RaceEvent
        """
        if self.http_client is None:
            # Puoi rimpiazzare questo con una lettura da cache locale / JSON
            raise NotImplementedError(
                "FISCalendarProvider.fetch_events: "
                "collega un http_client o una sorgente dati locale."
            )

        # Esempio di parametri tipici FIS (da adattare al parsing reale):
        params = {
            "sectorcode": "AL",                 # Sci alpino
            "seasoncode": str(season),
            "disciplinecode": "" if discipline is None else discipline.value,
            "nationcode": "" if nation is None else nation,
            "seasonselection": "",              # all season
            "eventselection": "",               # all competitions
            "gendercode": "",                   # M/F filter se ti serve
            "categorycode": "" if level is None else level,
        }

        html = self.http_client(self.BASE_URL, params)  # type: ignore

        # QUI: fare il parse dell'HTML con BeautifulSoup (in produzione)
        # Per ora ritorniamo una lista vuota / oppure potresti
        # popolarla leggendo da una cache JSON.
        events: List[RaceEvent] = []

        # Esempio di placeholder (puoi cancellarlo quando fai il parsing reale)
        # from datetime import date
        # events.append(
        #     RaceEvent(
        #         federation=self.federation,
        #         season=season,
        #         discipline=Discipline.GS,
        #         code="1234",
        #         name="Example FIS GS Race",
        #         nation="AUT",
        #         region=None,
        #         place="Sölden",
        #         resort="Rettenbach",
        #         start_date=date(season, 10, 25),
        #         end_date=date(season, 10, 25),
        #         category="WC",
        #         level="WC",
        #         gender="M",
        #         source_url=self.BASE_URL,
        #     )
        # )

        return events


# -----------------------------
#   Provider FISI (Italia + Regioni)
# -----------------------------


class FISICalendarProvider(BaseCalendarProvider):
    """
    Provider per calendari FISI:
    - calendario nazionale
    - calendari comitati regionali

    Riferimenti:
    - nazionale sci alpino: https://www.fisi.org/sci-alpino/calendario-gare/
    - comitati: https://comitati.fisi.org/{nome_comitato}/calendario/
    """

    federation = Federation.FISI

    NATIONAL_URL = "https://www.fisi.org/sci-alpino/calendario-gare/"
    COMMITTEE_BASE = "https://comitati.fisi.org/{slug}/calendario/"

    def __init__(
        self,
        http_client: Optional[Callable[[str, dict | None], str]] = None,
        committee_slugs: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        http_client: callable opzionale (url, params|None) -> HTML
        committee_slugs: mappa regione -> slug URL FISI, es:
            {
                "VENETO": "veneto",
                "ALPI_CENTRALI": "alpi-centrali",
                "TRENTINO": "trentino",
                ...
            }
        """
        self.http_client = http_client
        self.committee_slugs = committee_slugs or {}

    def fetch_events(
        self,
        season: int,
        discipline: Optional[Discipline] = None,
        nation: Optional[str] = None,   # di solito "ITA"
        region: Optional[str] = None,   # es. "VENETO", "ALPI_CENTRALI"
        category: Optional[str] = None,
        level: Optional[str] = None,
    ) -> List[RaceEvent]:
        if self.http_client is None:
            raise NotImplementedError(
                "FISICalendarProvider.fetch_events: "
                "collega un http_client o una sorgente dati locale."
            )

        events: List[RaceEvent] = []

        # 1) Calendario nazionale
        html_national = self.http_client(self.NATIONAL_URL, None)
        events.extend(
            self._parse_national_calendar_html(
                html_national,
                season=season,
                discipline=discipline,
                category=category,
                level=level,
            )
        )

        # 2) Comitati regionali (se nessuna regione specificata → tutti)
        target_regions = (
            [region] if region is not None else list(self.committee_slugs.keys())
        )

        for reg in target_regions:
            slug = self.committee_slugs.get(reg or "", None)
            if not slug:
                continue

            url = self.COMMITTEE_BASE.format(slug=slug)
            html_reg = self.http_client(url, None)
            events.extend(
                self._parse_committee_calendar_html(
                    html_reg,
                    season=season,
                    region=reg,
                    discipline=discipline,
                    category=category,
                    level=level,
                )
            )

        # filtro per nazione, se passato (anche se FISI è quasi solo ITA)
        if nation is not None:
            events = [e for e in events if e.nation == nation or e.nation is None]

        return events

    # -----------------------------
    #   Parser HTML (stubs)
    # -----------------------------

    def _parse_national_calendar_html(
        self,
        html: str,
        season: int,
        discipline: Optional[Discipline],
        category: Optional[str],
        level: Optional[str],
    ) -> List[RaceEvent]:
        """
        TODO: implementare parser HTML vero leggendo la tabella su fisi.org.
        Qui definisco solo la firma e i filtri logici.
        """
        # Usa BeautifulSoup in produzione:
        # - trova la tabella calendario
        # - estrai data, luogo, codice gara, categoria, livello, genere, disciplina
        # - mappa su RaceEvent
        return []

    def _parse_committee_calendar_html(
        self,
        html: str,
        season: int,
        region: Optional[str],
        discipline: Optional[Discipline],
        category: Optional[str],
        level: Optional[str],
    ) -> List[RaceEvent]:
        """
        TODO: parser per calendari dei comitati (Veneto, Alpi Centrali, ecc.).
        """
        return []


# -----------------------------
#   Servizio di alto livello
# -----------------------------


class RaceCalendarService:
    """
    Facciata unica: da qui la tua app chiede:
    - tutte le gare FIS/FISI
    - filtrate per stagione / disciplina / nazione / regione / categoria
    """

    def __init__(
        self,
        fis_provider: Optional[FISCalendarProvider] = None,
        fisi_provider: Optional[FISICalendarProvider] = None,
    ) -> None:
        self.fis_provider = fis_provider or FISCalendarProvider()
        self.fisi_provider = fisi_provider or FISICalendarProvider()

    def list_events(
        self,
        season: int,
        federation: Optional[Federation] = None,
        discipline: Optional[Discipline] = None,
        nation: Optional[str] = None,
        region: Optional[str] = None,
        category: Optional[str] = None,
        level: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        if federation in (None, Federation.FIS):
            try:
                events.extend(
                    self.fis_provider.fetch_events(
                        season=season,
                        discipline=discipline,
                        nation=nation,
                        region=None,
                        category=category,
                        level=level,
                    )
                )
            except NotImplementedError:
                pass

        if federation in (None, Federation.FISI):
            try:
                events.extend(
                    self.fisi_provider.fetch_events(
                        season=season,
                        discipline=discipline,
                        nation=nation,
                        region=region,
                        category=category,
                        level=level,
                    )
                )
            except NotImplementedError:
                pass

        # filtra per intervallo date se richiesto
        if start_date or end_date:
            events = [e for e in events if e.is_in_range(start_date, end_date)]

        return events

    @staticmethod
    def group_by_nation(events: Iterable[RaceEvent]) -> Dict[str, List[RaceEvent]]:
        grouped: Dict[str, List[RaceEvent]] = {}
        for e in events:
            key = e.nation or "UNK"
            grouped.setdefault(key, []).append(e)
        return grouped

    @staticmethod
    def group_by_region(events: Iterable[RaceEvent]) -> Dict[str, List[RaceEvent]]:
        grouped: Dict[str, List[RaceEvent]] = {}
        for e in events:
            key = e.region or "UNK"
            grouped.setdefault(key, []).append(e)
        return grouped
