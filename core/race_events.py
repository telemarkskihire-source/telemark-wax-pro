# core/race_events.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import List, Optional, Iterable, Dict, Callable

from bs4 import BeautifulSoup

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

        params = {
            "sectorcode": "AL",                 # Sci alpino
            "seasoncode": str(season),
            "disciplinecode": "" if discipline is None else discipline.value,
            "nationcode": "" if nation is None else nation,
            "seasonselection": "",
            "eventselection": "",
            "gendercode": "",
            "categorycode": "" if level is None else level,
        }

        html = self.http_client(self.BASE_URL, params)  # type: ignore

        # TODO: parsing reale con BeautifulSoup
        events: List[RaceEvent] = []
        return events


# -----------------------------
#   Provider FISI (Italia + Regioni)
# -----------------------------


class FISICalendarProvider(BaseCalendarProvider):
    """
    Provider per calendari FISI:
    - calendario nazionale
    - calendari comitati regionali
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

        if nation is not None:
            events = [e for e in events if e.nation == nation or e.nation is None]

        return events

    # ---------- PARSER NAZIONALE ----------

    def _parse_national_calendar_html(
        self,
        html: str,
        season: int,
        discipline: Optional[Discipline],
        category: Optional[str],
        level: Optional[str],
    ) -> List[RaceEvent]:
        """
        Parser indicativo per il calendario nazionale FISI.
        Va adattato all'HTML reale di fisi.org.
        """
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        table = soup.find("table")
        if table is None:
            return events

        header_row = table.find("tr")
        if not header_row:
            return events

        headers = [
            h.get_text(strip=True).lower()
            for h in header_row.find_all(["th", "td"])
        ]

        def col_index(name_substring: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if name_substring.lower() in h:
                    return i
            return None

        idx_date = col_index("data")
        idx_place = col_index("local")  # località
        idx_region = col_index("comit") or col_index("reg")
        idx_disc = col_index("disciplina")
        idx_cat = col_index("cat")
        idx_level = col_index("livello")
        idx_code = col_index("codice")
        idx_gender = col_index("genere")

        if idx_date is None or idx_place is None or idx_code is None:
            return events

        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < len(headers):
                continue

            raw_date = cells[idx_date]
            raw_place = cells[idx_place]
            raw_region = cells[idx_region] if idx_region is not None else ""
            raw_disc = cells[idx_disc] if idx_disc is not None else ""
            raw_cat = cells[idx_cat] if idx_cat is not None else ""
            raw_level = cells[idx_level] if idx_level is not None else ""
            raw_code = cells[idx_code]
            raw_gender = cells[idx_gender] if idx_gender is not None else ""

            try:
                d = datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                continue

            disc_enum: Optional[Discipline] = None
            if raw_disc:
                up = raw_disc.upper()
                if "SL" in up:
                    disc_enum = Discipline.SL
                elif "GS" in up or "GIG" in up:
                    disc_enum = Discipline.GS
                elif "SG" in up:
                    disc_enum = Discipline.SG
                elif "DH" in up or "DISCESA" in up:
                    disc_enum = Discipline.DH

            if discipline is not None and disc_enum is not None and disc_enum != discipline:
                continue

            if category is not None and category.lower() not in raw_cat.lower():
                continue
            if level is not None and level.lower() not in raw_level.lower():
                continue

            start_date = d
            end_date = d

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc_enum,
                code=raw_code,
                name=f"{raw_disc} {raw_place}",
                nation="ITA",
                region=raw_region or None,
                place=raw_place,
                resort=None,
                start_date=start_date,
                end_date=end_date,
                category=raw_cat or None,
                level=raw_level or None,
                gender=raw_gender or None,
                source_url=self.NATIONAL_URL,
            )
            events.append(ev)

        return events

    # ---------- PARSER COMITATI ----------

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
        Parser per i calendari dei comitati FISI.
        """
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        table = soup.find("table")
        if table is None:
            return events

        header_row = table.find("tr")
        if not header_row:
            return events

        headers = [
            h.get_text(strip=True).lower()
            for h in header_row.find_all(["th", "td"])
        ]

        def col_index(name_substring: str) -> Optional[int]:
            for i, h in enumerate(headers):
                if name_substring.lower() in h:
                    return i
            return None

        idx_date = col_index("data")
        idx_place = col_index("local")
        idx_disc = col_index("disciplina")
        idx_cat = col_index("cat")
        idx_level = col_index("livello")
        idx_code = col_index("codice")
        idx_gender = col_index("genere")

        if idx_date is None or idx_place is None or idx_code is None:
            return events

        for row in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < len(headers):
                continue

            raw_date = cells[idx_date]
            raw_place = cells[idx_place]
            raw_disc = cells[idx_disc] if idx_disc is not None else ""
            raw_cat = cells[idx_cat] if idx_cat is not None else ""
            raw_level = cells[idx_level] if idx_level is not None else ""
            raw_code = cells[idx_code]
            raw_gender = cells[idx_gender] if idx_gender is not None else ""

            try:
                d = datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                continue

            disc_enum: Optional[Discipline] = None
            if raw_disc:
                up = raw_disc.upper()
                if "SL" in up:
                    disc_enum = Discipline.SL
                elif "GS" in up or "GIG" in up:
                    disc_enum = Discipline.GS
                elif "SG" in up:
                    disc_enum = Discipline.SG
                elif "DH" in up or "DISCESA" in up:
                    disc_enum = Discipline.DH

            if discipline is not None and disc_enum is not None and disc_enum != discipline:
                continue

            if category is not None and category.lower() not in raw_cat.lower():
                continue
            if level is not None and level.lower() not in raw_level.lower():
                continue

            start_date = d
            end_date = d

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc_enum,
                code=raw_code,
                name=f"{raw_disc} {raw_place}",
                nation="ITA",
                region=region,
                place=raw_place,
                resort=None,
                start_date=start_date,
                end_date=end_date,
                category=raw_cat or None,
                level=raw_level or None,
                gender=raw_gender or None,
                source_url=None,
            )
            events.append(ev)

        return events


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
