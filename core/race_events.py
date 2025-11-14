# core/race_events.py

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List, Callable, Dict

from bs4 import BeautifulSoup


class Federation:
    FIS = "FIS"
    FISI = "FISI"


class Discipline:
    SL = "SL"
    GS = "GS"
    SG = "SG"
    DH = "DH"


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


class FISCalendarProvider(BaseCalendarProvider):
    """
    Provider FIS basato su Neveitalia:
      - WC maschile: https://www.neveitalia.it/sport/scialpino/calendario
      - WC femminile: https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile
    """

    federation = Federation.FIS

    BASE_URL_MEN = "https://www.neveitalia.it/sport/scialpino/calendario"
    BASE_URL_WOMEN = "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"

    DATE_LINE_RE = re.compile(
        r"^(?P<date>\d{4}-\d{2}-\d{2})(?:\s+(?P<time>\d{2}:\d{2}))?\s+(?P<rest>.+)$"
    )

    def __init__(self, http_client: Callable[[str, Optional[dict]], str]):
        self.http_client = http_client

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

        # uomini
        try:
            html_m = self.http_client(self.BASE_URL_MEN, {})
            events += self._parse_neveitalia_html(
                html=html_m,
                season=season,
                discipline_filter=discipline,
                gender="M",
                source_url=self.BASE_URL_MEN,
            )
        except Exception:
            pass

        # donne
        try:
            html_f = self.http_client(self.BASE_URL_WOMEN, {})
            events += self._parse_neveitalia_html(
                html=html_f,
                season=season,
                discipline_filter=discipline,
                gender="F",
                source_url=self.BASE_URL_WOMEN,
            )
        except Exception:
            pass

        if nation:
            events = [e for e in events if (e.nation or "").upper() == nation.upper()]

        events.sort(key=lambda ev: ev.start_date)
        return events

    def _parse_neveitalia_html(
        self,
        html: str,
        season: int,
        discipline_filter: Optional[str],
        gender: Optional[str],
        source_url: str,
    ) -> List[RaceEvent]:
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
            rest = m.group("rest")

            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if d.year not in (season, season + 1):
                continue

            loc, event_name = self._split_location_event(rest)
            nation = self._extract_nation_from_location(loc)

            disc = self._map_discipline(event_name)
            if discipline_filter and disc and disc != discipline_filter:
                continue

            level = "WC"
            category = "WC"

            g = gender
            if "Maschile" in event_name:
                g = "M"
            elif "Femminile" in event_name:
                g = "F"

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
        rest = rest.strip()
        if ")" in rest:
            idx = rest.rfind(")")
            location = rest[: idx + 1].strip()
            event_name = rest[idx + 1 :].strip() or location
            return location, event_name
        parts = rest.split(" ", 1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        return rest, rest

    @staticmethod
    def _extract_nation_from_location(location: str) -> Optional[str]:
        m = re.search(r"\(([A-Z]{3})\)", location)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _map_discipline(event_name: str) -> Optional[str]:
        up = event_name.upper()
        if "GIGANTE" in up or " GS" in up:
            return Discipline.GS
        if "SLALOM" in up or " SL" in up:
            if "GIGANTE" not in up:
                return Discipline.SL
        if "SUPER-G" in up or "SUPER G" in up or " SUPERG" in up or " SG" in up:
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
        clean_place = (
            place.replace(" ", "_")
            .replace("/", "_")
            .replace("(", "")
            .replace(")", "")
        )
        parts = ["NEVE", str(season), date_str, clean_place]
        if disc:
            parts.append(disc)
        if gender:
            parts.append(gender)
        return "-".join(parts)


class FISICalendarProvider(BaseCalendarProvider):
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
        # placeholder finché non troviamo una sorgente FISI robusta
        return []


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
