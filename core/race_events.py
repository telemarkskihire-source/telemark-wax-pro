# core/race_events.py
# Telemark · Pro Wax & Tune
# Providers:
#   - FIS: scraping puro da Neveitalia (maschile + femminile)
#   - ASIVA: gare Valle d’Aosta, inserite da tabella Asiva (dic 2025 + apr 2026)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import List, Optional
import re

import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
# ENUM & MODELLO
# ---------------------------------------------------------------------------

class Federation(str, Enum):
    FIS = "FIS"
    ASIVA = "ASIVA"   # Comitato Valdostano Asiva


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
    category: Optional[str] = None
    raw_type: Optional[str] = None
    level: Optional[str] = None

    @property
    def is_future(self) -> bool:
        return self.start_date >= date.today()


# ---------------------------------------------------------------------------
# UTILITY
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


def _parse_date_it_dd_mmm_yyyy(raw: str) -> Optional[date]:
    """
    Formati tipo:
      - '9 dic 2025'
      - '10 apr 2026'
    """
    try:
        parts = raw.strip().lower().split()
        if len(parts) != 3:
            return None
        day = int(parts[0])
        month = _MONTHS_IT.get(parts[1])
        year = int(parts[2])
        if not month:
            return None
        return date(year, month, day)
    except Exception:
        return None


def _map_discipline(text: str) -> Discipline:
    """
    Mappa descrizione evento (es. 'Slalom Maschile', 'GS', 'SX') nel tuo enum Discipline.
    """
    t = (text or "").upper()

    # prima i codici “secchi”
    if "SL" in t:
        return Discipline.SL
    if "GS" in t or "GIGANTE" in t:
        return Discipline.GS
    if "SG" in t or "SUPER-G" in t or "SUPER G" in t:
        return Discipline.SG
    if "DH" in t or "DOWNHILL" in t or "DISCESA" in t:
        return Discipline.DH
    if "AC" in t or "COMB" in t:
        try:
            return Discipline.AC  # type: ignore[attr-defined]
        except Exception:
            return Discipline.GS
    if "SX" in t:  # ski cross ecc -> fallback
        return Discipline.GS

    # fallback: GS
    return Discipline.GS


# ---------------------------------------------------------------------------
# FIS PROVIDER — SCRAPING NEVEITALIA (MASCHILE + FEMMINILE)
# ---------------------------------------------------------------------------

class FISCalendarProvider:
    """
    Scraping da Neveitalia:

    - Maschile:
      https://www.neveitalia.it/sport/scialpino/calendario
    - Femminile:
      https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile

    La pagina elenca righe testo del tipo:
      '2025-10-26 Soelden (AUT) Slalom Gigante Maschile'
    che qui vengono intercettate via regex.
    """

    BASE_URLS = [
        "https://www.neveitalia.it/sport/scialpino/calendario",
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile",
    ]

    UA = {"User-Agent": "telemark-wax-pro/5.0 (FIS-Calendar-Scraper)"}

    _DATE_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(.+)$")

    def _fetch(self, url: str) -> str:
        r = requests.get(url, headers=self.UA, timeout=15)
        r.raise_for_status()
        return r.text

    def _parse_events_from_html(self, html: str) -> List[RaceEvent]:
        soup = BeautifulSoup(html, "html.parser")

        # prendiamo tutto il testo principale, con separatore di linea
        text = soup.get_text("\n", strip=True)

        events: List[RaceEvent] = []

        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue

            m = self._DATE_LINE_RE.match(line)
            if not m:
                continue

            date_str = m.group(1)
            rest = m.group(2)

            # richiediamo almeno una parentesi per isolare il luogo
            if "(" not in rest or ")" not in rest:
                continue

            close_idx = rest.find(")")
            place = rest[: close_idx + 1].strip()
            event_name = rest[close_idx + 1 :].strip(" -·")

            if not event_name:
                continue

            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            # nazione dalle parentesi, es. '(AUT)'
            nation = None
            m_nat = re.search(r"\(([A-Z]{3})\)", place)
            if m_nat:
                nation = m_nat.group(1)

            ev = RaceEvent(
                federation=Federation.FIS,
                codex=None,
                name=event_name,
                place=place,
                discipline=_map_discipline(event_name),
                start_date=dt,
                end_date=dt,
                nation=nation,
                region=None,
                category="WC",
                raw_type="FIS_WC",
                level="WC",
            )
            events.append(ev)

        return events

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        all_events: List[RaceEvent] = []

        for url in self.BASE_URLS:
            try:
                html = self._fetch(url)
                all_events.extend(self._parse_events_from_html(html))
            except Exception:
                # se una delle due pagine fallisce, continuiamo comunque
                continue

        # filtro per stagione FIS: [1 luglio season; 30 giugno season+1]
        season_start = date(season, 7, 1)
        season_end = date(season + 1, 6, 30)
        all_events = [
            ev
            for ev in all_events
            if season_start <= ev.start_date <= season_end
        ]

        # filtro disciplina (stringa tipo 'GS', 'SL', ecc.)
        if discipline_filter:
            code = discipline_filter.strip().upper()
            all_events = [
                ev
                for ev in all_events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        # eventuale filtro nazione
        if nation_filter:
            nf = nation_filter.strip().upper()
            all_events = [
                ev for ev in all_events
                if (ev.nation or "").upper() == nf
            ]

        return all_events


# ---------------------------------------------------------------------------
# ASIVA PROVIDER — DATI DA PAGINE ASIVA (DIC 2025 + APR 2026)
# ---------------------------------------------------------------------------

class ASIVACalendarProvider:
    """
    Calendario Asiva 2025-26 per Sci Alpino.

    I dati sono stati incollati a mano da:
      - Mese dicembre 2025
      - Mese aprile 2026

    raw_data: lista di tuple:
      (codex, data_it, spec, localita, denominazione, categoria_opzionale)
    """

    RAW_EVENTS = [
        # --- DICEMBRE 2025 ---
        ("ITA0857", "9 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
        ("ITA5829", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
        ("ITA0859", "10 dic 2025", "GS", "Courmayeur", "Trofeo ODL"),
        ("AA0001", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
        ("AA0002", "16 dic 2025", "GS", "Pila - Gressan", "Top 50"),
        ("AA0003", "16 dic 2025", "SL", "Pila - Gressan", "Top 50"),
        ("AA0004", "16 dic 2025", "SL", "Pila - Gressan", "Top 50"),
        ("AA0005", "17 dic 2025", "SL", "Pila - Gressan", "Top 50"),
        ("AA0006", "17 dic 2025", "SL", "Pila - Gressan", "Top 50"),
        ("AA0007", "17 dic 2025", "GS", "Pila - Gressan", "Top 50"),
        ("AA0008", "17 dic 2025", "GS", "Pila - Gressan", "Top 50"),
        ("XA0184", "19 dic 2025", "GS", "Pila - Gressan", "Trofeo Coni"),
        ("XA0185", "19 dic 2025", "GS", "Pila - Gressan", "Trofeo Coni"),
        ("XA0186", "20 dic 2025", "SL", "Pila - Gressan", "Trofeo Coni"),
        ("XA0187", "20 dic 2025", "SL", "Pila - Gressan", "Trofeo Coni"),
        ("ITA5851", "20 dic 2025", "SL", "La Thuile", "Memorial Menel"),
        ("ITA0883", "20 dic 2025", "SL", "La Thuile", "Memorial Menel"),
        ("ITA5855", "21 dic 2025", "SL", "La Thuile", "Memorial Menel"),
        ("ITA0887", "21 dic 2025", "SL", "La Thuile", "Memorial Menel"),
        ("AA0009", "21 dic 2025", "SL", "Valtournenche", "Trofeo Igor Gorgonzola Flipper"),
        ("AA0010", "21 dic 2025", "SL", "Valtournenche", "Trofeo Igor Gorgonzola Flipper"),
        ("AA0011", "22 dic 2025", "SL", "La Thuile", "Memorial Edoardo Camardella"),
        ("AA0012", "22 dic 2025", "SL", "La Thuile", "Memorial Edoardo Camardella"),
        ("ITA5858", "22 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
        ("ITA0890", "22 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
        ("ITA5862", "23 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
        ("ITA0894", "23 dic 2025", "GS", "Frachey - Ayas", "Trofeo Pulverit"),
        ("AA0013", "23 dic 2025", "SL", "Pila - Gressan", "Coppa Valle d'Aosta Spettacolo Flipper"),
        ("AA0014", "23 dic 2025", "SL", "Pila - Gressan", "Coppa Valle d'Aosta Spettacolo Flipper"),
        ("AA0015", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0020", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0017", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0022", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0018", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0023", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0016", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0021", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0019", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),
        ("AA0024", "23 dic 2025", "GS", "Torgnon", "Trofeo Sci Club Torgnon"),

        # --- APRILE 2026 (pagina Asiva Mese = Aprile) ---
        ("XA0148", "8 apr 2026", "GS", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0149", "8 apr 2026", "GS", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0150", "8 apr 2026", "SL", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0151", "8 apr 2026", "SL", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0164", "9 apr 2026", "PROVA SG", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0165", "9 apr 2026", "PROVA SG", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0166", "9 apr 2026", "PROVA SG", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0167", "9 apr 2026", "PROVA SG", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0152", "10 apr 2026", "SG", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0153", "10 apr 2026", "SG", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0154", "10 apr 2026", "SG", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0155", "10 apr 2026", "SG", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0156", "11 apr 2026", "SX", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0157", "11 apr 2026", "SX", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0158", "11 apr 2026", "GS", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0159", "11 apr 2026", "GS", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0160", "12 apr 2026", "SL", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0161", "12 apr 2026", "SL", "Pila - Gressan", "Campionati Italiani Allievi"),
        ("XA0162", "12 apr 2026", "SX", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("XA0163", "12 apr 2026", "SX", "Pila - Gressan", "Campionati Italiani Ragazzi"),
        ("AA0243", "11 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
        ("AA0244", "11 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
        ("AA0245", "11 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
        ("AA0246", "11 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
        ("AA0247", "12 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
        ("AA0248", "12 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
        ("AA0249", "12 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
        ("AA0250", "12 apr 2026", "GS", "Valtournenche", "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
        ("ITA6087", "15 apr 2026", "SL", "Valtournenche", "Trofeo Comune di Valtournenche"),
        ("ITA1117", "15 apr 2026", "SL", "Valtournenche", "Trofeo Comune di Valtournenche"),
        ("ITA6088", "16 apr 2026", "SL", "Valtournenche", "Trofeo Comune di Valtournenche"),
        ("ITA1118", "16 apr 2026", "SL", "Valtournenche", "Trofeo Comune di Valtournenche"),
        ("ITA6089", "17 apr 2026", "GS", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
        ("ITA1119", "17 apr 2026", "GS", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
        ("ITA6090", "18 apr 2026", "GS", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
        ("ITA1120", "18 apr 2026", "GS", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
        ("XA0168", "17 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0169", "17 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0170", "17 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0172", "17 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0171", "17 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0173", "17 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0174", "18 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0176", "18 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0177", "18 apr 2026", "SL", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0178", "18 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0179", "18 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0180", "19 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0181", "19 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0182", "19 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
        ("XA0183", "19 apr 2026", "GS", "Pila - Gressan", "Memorial Fosson Criterium Italiano a Squadre"),
    ]

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
    ) -> List[RaceEvent]:

        events: List[RaceEvent] = []

        for codex, date_raw, spec, place, name in self.RAW_EVENTS:
            dt = _parse_date_it_dd_mmm_yyyy(date_raw)
            if not dt:
                continue

            # filtro stagione: stesso range usato per FIS
            season_start = date(season, 7, 1)
            season_end = date(season + 1, 6, 30)
            if not (season_start <= dt <= season_end):
                continue

            ev = RaceEvent(
                federation=Federation.ASIVA,
                codex=codex,
                name=name,
                place=place,
                discipline=_map_discipline(spec),
                start_date=dt,
                end_date=dt,
                nation="ITA",
                region="Valle d'Aosta",
                category=None,
                raw_type="ASIVA",
                level=None,
            )
            events.append(ev)

        # filtro disciplina
        if discipline_filter:
            code = discipline_filter.strip().upper()
            events = [
                ev
                for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
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
    ) -> List[RaceEvent]:

        events: List[RaceEvent] = []

        # FIS
        if federation is None or federation == Federation.FIS:
            try:
                events.extend(
                    self._fis.list_events(
                        season=season,
                        discipline_filter=discipline,
                        nation_filter=nation,
                        region_filter=region,
                    )
                )
            except Exception:
                pass

        # ASIVA
        if federation is None or federation == Federation.ASIVA:
            try:
                events.extend(
                    self._asiva.list_events(
                        season=season,
                        discipline_filter=discipline,
                        nation_filter=nation,
                        region_filter=region,
                    )
                )
            except Exception:
                pass

        # filtro per mese
        if month is not None:
            events = [ev for ev in events if ev.start_date.month == month]

        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
