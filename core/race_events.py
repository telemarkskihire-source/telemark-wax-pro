# core/race_events.py
# Telemark · Pro Wax & Tune
#
# Providers:
# - FIS: scraping NeveItalia (uomini + donne, best effort; se fallisce => lista vuota)
# - ASIVA: gare incollate manualmente (Valle d’Aosta) con filtri mese & categoria (Partec.)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
# ENUM & MODELLO
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
    category: Optional[str] = None  # Partec. per ASIVA
    raw_type: Optional[str] = None
    level: Optional[str] = None

    @property
    def is_future(self) -> bool:
        return self.start_date >= date.today()


# ---------------------------------------------------------------------------
# UTIL COMUNI
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
    Formati supportati:
    - "9 dic 2025"
    - "10 gen 2026"
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
    t = (text or "").upper()

    if "SL" in t:
        return Discipline.SL
    if "GS" in t:
        return Discipline.GS
    if "SG" in t:
        return Discipline.SG
    if "DH" in t:
        return Discipline.DH
    if "SX" in t:
        # skicross / similar → se hai AC nel tuo enum puoi usarlo, altrimenti GS
        try:
            return Discipline.AC  # type: ignore[attr-defined]
        except Exception:
            return Discipline.GS
    if "AC" in t or "COMB" in t:
        try:
            return Discipline.AC  # type: ignore[attr-defined]
        except Exception:
            return Discipline.GS

    return Discipline.GS


# ---------------------------------------------------------------------------
# FIS PROVIDER — NEVEITALIA (best effort)
# ---------------------------------------------------------------------------

class FISCalendarProvider:
    """
    Scraping da NeveItalia (struttura suscettibile a cambi, quindi best effort).
    - Maschile:  https://www.neveitalia.it/sport/scialpino/calendario
    - Femminile: https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile
    Se qualcosa va storto restituisce semplicemente [].
    """

    BASE_URLS = [
        "https://www.neveitalia.it/sport/scialpino/calendario",
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile",
    ]

    UA = {"User-Agent": "telemark-wax-pro/4.0"}

    def _fetch(self, url: str) -> str:
        r = requests.get(url, headers=self.UA, timeout=15)
        r.raise_for_status()
        return r.text

    def _parse(self, html: str) -> List[RaceEvent]:
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        # Neveitalia tipicamente usa una tabella per il calendario.
        # Strategia: scorriamo tutte le <tr> con almeno 4 <td>:
        # [data, località, disciplina, nome gara, ...]
        for row in soup.find_all("tr"):
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 4:
                continue

            raw_date, place, disc_txt, name = cols[0], cols[1], cols[2], cols[3]

            dt = _parse_date_it(raw_date)
            if not dt:
                continue

            ev = RaceEvent(
                federation=Federation.FIS,
                codex=None,
                name=name,
                place=place or "Località FIS",
                discipline=_map_discipline(disc_txt),
                start_date=dt,
                end_date=dt,
                nation=None,
                region=None,
                category=None,
                raw_type="FIS",
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
        month_filter: Optional[int] = None,
    ) -> List[RaceEvent]:
        all_events: List[RaceEvent] = []

        for url in self.BASE_URLS:
            try:
                html = self._fetch(url)
                all_events.extend(self._parse(html))
            except Exception:
                # Non blocchiamo l'app se NeveItalia cambia markup
                continue

        # filtro stagione (anno di start della stagione + successivo)
        all_events = [
            ev
            for ev in all_events
            if ev.start_date.year in (season, season + 1)
        ]

        # filtro mese (1–12)
        if month_filter:
            all_events = [ev for ev in all_events if ev.start_date.month == month_filter]

        # filtro disciplina
        if discipline_filter:
            code = discipline_filter.strip().upper()
            all_events = [
                ev
                for ev in all_events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        return all_events


# ---------------------------------------------------------------------------
# ASIVA PROVIDER — DATI INCOLLATI (NO SCRAPING)
# ---------------------------------------------------------------------------

# raw_data: (codex, data_txt, spec, partec, place, name)
_ASIVA_RAW_EVENTS = [
    # --- DICEMBRE 2025 -----------------------------------------------------
    ("ITA0857", "9 dic 2025", "GS", "M", "Courmayeur", "Trofeo ODL"),
    ("ITA5829", "10 dic 2025", "GS", "F", "Courmayeur", "Trofeo ODL"),
    ("ITA0859", "10 dic 2025", "GS", "M", "Courmayeur", "Trofeo ODL"),
    ("AA0001", "16 dic 2025", "GS", "A_M", "Pila - Gressan", "Top 50"),
    ("AA0002", "16 dic 2025", "GS", "A_F", "Pila - Gressan", "Top 50"),
    ("AA0003", "16 dic 2025", "SL", "R_M", "Pila - Gressan", "Top 50"),
    ("AA0004", "16 dic 2025", "SL", "R_F", "Pila - Gressan", "Top 50"),
    ("AA0005", "17 dic 2025", "SL", "A_M", "Pila - Gressan", "Top 50"),
    ("AA0006", "17 dic 2025", "SL", "A_F", "Pila - Gressan", "Top 50"),
    ("AA0007", "17 dic 2025", "GS", "R_M", "Pila - Gressan", "Top 50"),
    ("AA0008", "17 dic 2025", "GS", "R_F", "Pila - Gressan", "Top 50"),
    ("XA0184", "19 dic 2025", "GS", "R_M", "Pila - Gressan", "Trofeo Coni"),
    ("XA0185", "19 dic 2025", "GS", "R_F", "Pila - Gressan", "Trofeo Coni"),
    ("XA0186", "20 dic 2025", "SL", "R_M", "Pila - Gressan", "Trofeo Coni"),
    ("XA0187", "20 dic 2025", "SL", "R_F", "Pila - Gressan", "Trofeo Coni"),
    ("ITA5851", "20 dic 2025", "SL", "F", "La Thuile", "Memorial Menel"),
    ("ITA0883", "20 dic 2025", "SL", "M", "La Thuile", "Memorial Menel"),
    ("ITA5855", "21 dic 2025", "SL", "F", "La Thuile", "Memorial Menel"),
    ("ITA0887", "21 dic 2025", "SL", "M", "La Thuile", "Memorial Menel"),
    ("AA0009", "21 dic 2025", "SL", "A_M", "Valtournenche", "Trofeo Igor Gorgonzola Flipper"),
    ("AA0010", "21 dic 2025", "SL", "A_F", "Valtournenche", "Trofeo Igor Gorgonzola Flipper"),
    ("AA0011", "22 dic 2025", "SL", "A_M", "La Thuile", "Memorial Edoardo Camardella"),
    ("AA0012", "22 dic 2025", "SL", "A_F", "La Thuile", "Memorial Edoardo Camardella"),
    ("ITA5858", "22 dic 2025", "GS", "F", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA0890", "22 dic 2025", "GS", "M", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA5862", "23 dic 2025", "GS", "F", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA0894", "23 dic 2025", "GS", "M", "Frachey - Ayas", "Trofeo Pulverit"),
    ("AA0013", "23 dic 2025", "SL", "R_M", "Pila - Gressan", "Coppa Valle d'Aosta Spettacolo Flipper"),
    ("AA0014", "23 dic 2025", "SL", "R_F", "Pila - Gressan", "Coppa Valle d'Aosta Spettacolo Flipper"),
    ("AA0015", "23 dic 2025", "GS", "GSM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0020", "23 dic 2025", "GS", "GSM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0017", "23 dic 2025", "GS", "MAM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0022", "23 dic 2025", "GS", "MAM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0018", "23 dic 2025", "GS", "MBM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0023", "23 dic 2025", "GS", "MBM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0016", "23 dic 2025", "GS", "GSF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0021", "23 dic 2025", "GS", "GSF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0019", "23 dic 2025", "GS", "MCF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0024", "23 dic 2025", "GS", "MCF", "Torgnon", "Trofeo Sci Club Torgnon"),

    # --- APRILE 2026 -------------------------------------------------------
    ("XA0148", "8 apr 2026", "GS", "A_M", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0149", "8 apr 2026", "GS", "A_F", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0150", "8 apr 2026", "SL", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0151", "8 apr 2026", "SL", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0164", "9 apr 2026", "SG", "A_M", "Pila - Gressan", "Campionati Italiani Allievi (prova SG)"),
    ("XA0165", "9 apr 2026", "SG", "A_F", "Pila - Gressan", "Campionati Italiani Allievi (prova SG)"),
    ("XA0166", "9 apr 2026", "SG", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi (prova SG)"),
    ("XA0167", "9 apr 2026", "SG", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi (prova SG)"),
    ("XA0152", "10 apr 2026", "SG", "A_M", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0153", "10 apr 2026", "SG", "A_F", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0154", "10 apr 2026", "SG", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0155", "10 apr 2026", "SG", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0156", "11 apr 2026", "SX", "A_M", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0157", "11 apr 2026", "SX", "A_F", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0158", "11 apr 2026", "GS", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0159", "11 apr 2026", "GS", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0160", "12 apr 2026", "SL", "A_M", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0161", "12 apr 2026", "SL", "A_F", "Pila - Gressan", "Campionati Italiani Allievi"),
    ("XA0162", "12 apr 2026", "SX", "R_M", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("XA0163", "12 apr 2026", "SX", "R_F", "Pila - Gressan", "Campionati Italiani Ragazzi"),
    ("AA0243", "11 apr 2026", "GS", "P1_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0244", "11 apr 2026", "GS", "P1_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0245", "11 apr 2026", "GS", "P2_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0246", "11 apr 2026", "GS", "P2_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0247", "12 apr 2026", "GS", "U1_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0248", "12 apr 2026", "GS", "U1_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0249", "12 apr 2026", "GS", "U2_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0250", "12 apr 2026", "GS", "U2_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("ITA6087", "15 apr 2026", "SL", "F", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA1117", "15 apr 2026", "SL", "M", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA6088", "16 apr 2026", "SL", "F", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA1118", "16 apr 2026", "SL", "M", "Valtournenche", "Trofeo Comune di Valtournenche"),
    ("ITA6089", "17 apr 2026", "GS", "F", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("ITA1119", "17 apr 2026", "GS", "M", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("ITA6090", "18 apr 2026", "GS", "F", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("ITA1120", "18 apr 2026", "GS", "M", "Frachey - Ayas", "Coppa Sci Club Val d'Ayas"),
    ("XA0168", "17 apr 2026", "GS", "A_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0169", "17 apr 2026", "GS", "A_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0170", "17 apr 2026", "SL", "R_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0172", "17 apr 2026", "SL", "R_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0171", "17 apr 2026", "SL", "R_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0173", "17 apr 2026", "SL", "R_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0174", "18 apr 2026", "SL", "A_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0176", "18 apr 2026", "SL", "A_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0177", "18 apr 2026", "SL", "A_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0178", "18 apr 2026", "GS", "R_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0179", "18 apr 2026", "GS", "R_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0180", "19 apr 2026", "GS", "A_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0181", "19 apr 2026", "GS", "A_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0182", "19 apr 2026", "GS", "R_M", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
    ("XA0183", "19 apr 2026", "GS", "R_F", "Pila - Gressan",
     "Memorial Fosson Criterium Italiano a Squadre"),
]

# lista di codici Partec. disponibili (per selectbox in UI)
ASIVA_PARTEC_CODES: List[str] = sorted(
    {row[3] for row in _ASIVA_RAW_EVENTS if row[3]}
)


class ASIVACalendarProvider:
    """
    Provider ASIVA basato su dati incollati a mano.
    """

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
        month_filter: Optional[int] = None,
        category_filter: Optional[str] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        for codex, date_raw, spec, partec, place, name in _ASIVA_RAW_EVENTS:
            dt = _parse_date_it(date_raw)
            if not dt:
                continue

            # stagione 2025-26 => anni season o season+1
            if dt.year not in (season, season + 1):
                continue

            if month_filter and dt.month != month_filter:
                continue

            if category_filter and partec != category_filter:
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
                category=partec,
                raw_type="ASIVA",
                level=None,
            )
            events.append(ev)

        # filtro disciplina (stringa tipo "GS", "SL", …)
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
        category: Optional[str] = None,
    ) -> List[RaceEvent]:
        events: List[RaceEvent] = []

        # FIS
        if federation is None or federation == Federation.FIS:
            try:
                events_fis = self._fis.list_events(
                    season=season,
                    discipline_filter=discipline,
                    nation_filter=nation,
                    region_filter=region,
                    month_filter=month,
                )
                events.extend(events_fis)
            except Exception:
                pass

        # ASIVA
        if federation is None or federation == Federation.ASIVA:
            try:
                events_asiva = self._asiva.list_events(
                    season=season,
                    discipline_filter=discipline,
                    nation_filter=nation,
                    region_filter=region,
                    month_filter=month,
                    category_filter=category,
                )
                events.extend(events_asiva)
            except Exception:
                pass

        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
