import requests
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, List, Callable, Dict

from bs4 import BeautifulSoup

# ---------------------------------------------------------
# ENUM / COSTANTI BASE
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
# FIS — FULL REAL-TIME PARSER
# ---------------------------------------------------------

class FISCalendarProvider(BaseCalendarProvider):
    federation = Federation.FIS

    BASE_URL = "https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html"

    def __init__(self, http_client: Callable[[str, dict], str]):
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

        # categorycode obbligatorio per FIS
        if level:
            categorycode = level.upper()
        elif category:
            categorycode = category.upper()
        else:
            categorycode = "WC"

        params = {
            "categorycode": categorycode,
            "disciplinecode": "" if discipline is None else discipline,
            "eventselection": "",
            "gendercode": "",
            "nationcode": "" if nation is None else nation,
            "place": "",
            "racecodex": "",
            "racedate": "",
            "saveselection": "-1",
            "seasoncode": str(season),
            "seasonmonth": f"X-{season}",
            "seasonselection": "",
            "sectorcode": "AL",
        }

        html = self.http_client(self.BASE_URL, params)
        return self._parse_fis_html(html, season, discipline, categorycode)

    def _parse_fis_html(
        self,
        html: str,
        season: int,
        discipline_filter: Optional[str],
        category: str,
    ) -> List[RaceEvent]:

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        rows = table.find_all("tr")
        if len(rows) <= 1:
            return []

        # header
        headers = [
            h.get_text(strip=True).lower()
            for h in rows[0].find_all(["td", "th"])
        ]

        def col(name):
            for i, h in enumerate(headers):
                if name in h:
                    return i
            return None

        idx_date = col("date")
        idx_place = col("place")
        idx_nsa = col("nsa")
        idx_cat_evt = col("category") or col("event")
        idx_gender = col("gender")
        idx_codex = col("codex")

        events = []

        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < len(headers):
                continue

            raw_date = cells[idx_date] if idx_date is not None else ""
            raw_place = cells[idx_place] if idx_place is not None else ""
            raw_nsa = cells[idx_nsa] if idx_nsa is not None else ""
            raw_cat_evt = cells[idx_cat_evt] if idx_cat_evt is not None else ""
            raw_gender = cells[idx_gender] if idx_gender is not None else ""
            raw_codex = cells[idx_codex] if idx_codex is not None else ""

            # parse data
            try:
                parts = raw_date.split()
                day = parts[0].split("-")[0]
                month = parts[1]
                year = parts[2]
                d = datetime.strptime(
                    f"{day} {month} {year}", "%d %b %Y"
                ).date()
            except:
                continue

            # disciplina
            up = raw_cat_evt.upper()
            disc = None
            if "SL" in up and not "PSL" in up:
                disc = "SL"
            elif "GS" in up:
                disc = "GS"
            elif "SG" in up:
                disc = "SG"
            elif "DH" in up or "DOWNHILL" in up:
                disc = "DH"

            if discipline_filter and disc and disc != discipline_filter:
                continue

            # livello
            level = None
            for code in ["WC", "EC", "FIS", "ENL", "NJR", "CIT", "NC"]:
                if code in up:
                    level = code
                    break

            code = raw_codex or f"{season}-{raw_place}-{raw_date}"

            ev = RaceEvent(
                federation=self.federation,
                season=season,
                discipline=disc,
                code=code,
                name=raw_cat_evt or raw_place,
                nation=raw_nsa or None,
                region=None,
                place=raw_place,
                resort=None,
                start_date=d,
                end_date=d,
                category=category,
                level=level,
                gender=raw_gender or None,
                source_url=self.BASE_URL,
            )
            events.append(ev)

        return events

# ---------------------------------------------------------
# FISI — BLOCCATO (403) → placeholder per ora
# ---------------------------------------------------------

class FISICalendarProvider(BaseCalendarProvider):
    federation = Federation.FISI

    def __init__(
        self,
        http_client,
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
    ):
        # temporaneo fino al backend offline
        return []

# ---------------------------------------------------------
# SERVIZIO UNIFICATO
# ---------------------------------------------------------

class RaceCalendarService:
    def __init__(self, fis_provider, fisi_provider):
        self.fis = fis_provider
        self.fisi = fisi_provider

    def list_events(
        self,
        season,
        federation: Optional[str],
        discipline: Optional[str],
        nation: Optional[str],
        region: Optional[str],
    ) -> List[RaceEvent]:

        result = []

        if federation in (Federation.FIS, None):
            try:
                result += self.fis.fetch_events(season, discipline, nation)
            except Exception:
                pass

        if federation in (Federation.FISI, None):
            try:
                result += self.fisi.fetch_events(season, discipline, nation, region)
            except Exception:
                pass

        # ordina per data
        result.sort(key=lambda ev: ev.start_date)
        return result
