# core/race_events.py
# Telemark · Pro Wax & Tune
#
# Providers:
# - FIS: scraping NeveItalia (uomini + donne) — parser robusto su tabelle calendario
# - ASIVA: calendario Valle d’Aosta codificato a mano (estratto),
#          con filtri per mese e categoria (Partec.)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Tuple

import re
import unicodedata

import requests
from bs4 import BeautifulSoup

from .race_tuning import Discipline


# ---------------------------------------------------------------------------
# ENUM & MODEL
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
    category: Optional[str] = None  # Partec (A_M, U1_F, ecc.)
    raw_type: Optional[str] = None  # Tipo (FIS_NJR, PM_REG, …)
    level: Optional[str] = None     # WC, REG, ecc.

    @property
    def is_future(self) -> bool:
        return self.start_date >= date.today()


# ---------------------------------------------------------------------------
# DATE & DISCIPLINE HELPERS
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

# varianti possibili tipo "ottobre", "dicembre" ecc.
_MONTHS_IT_FULL = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def _normalize_text(s: str) -> str:
    """Normalizza testo per confronti: maiuscolo, senza accenti, trim."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.strip().upper()


def _parse_date_it(raw: str) -> Optional[date]:
    """
    Formati supportati (molto permissivi, per adattarsi a NeveItalia / ASIVA):
    - "9 dic 2025"
    - "10 gennaio 2026"
    - "09/12/2025", "09-12-2025", "09.12.2025"
    - "9 dic"  (in questo caso si assume stagione "corrente" o successiva -> usiamo l'anno corrente)
    """
    if not raw:
        return None

    s = raw.strip().lower()

    # --- 1) formato numerico tipo 09/12/2025, 09-12-2025, 09.12.2025 ---
    m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\s*$", s)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        if year < 100:  # tipo '25' -> 2025
            year = 2000 + year
        try:
            return date(year, month, day)
        except Exception:
            return None

    # --- 2) formato testo italiano tipo "9 dic 2025" o "10 gennaio 2026" ---
    parts = s.split()
    try:
        # se non abbiamo 2 o 3 parti, lasciamo perdere
        if len(parts) < 2:
            return None

        day = int(parts[0])

        year: Optional[int] = None
        month: Optional[int] = None

        # cerca un token che sia l'anno
        for token in parts[1:]:
            if token.isdigit():
                yy = int(token)
                if yy < 100:  # '25' -> 2025
                    yy = 2000 + yy
                year = yy
                break

        # se l'anno non è presente, usiamo l'anno corrente
        if year is None:
            year = date.today().year

        # cerca un token che sia il mese (abbreviazione o mese completo)
        for token in parts[1:]:
            mm = _MONTHS_IT.get(token[:3])
            if mm:
                month = mm
                break
            mm_full = _MONTHS_IT_FULL.get(token)
            if mm_full:
                month = mm_full
                break

        if not month:
            return None

        return date(year, month, day)
    except Exception:
        return None


def _map_discipline(text: str) -> Discipline:
    t = (text or "").upper()

    # ci basta riconoscere la disciplina base
    if "SL" in t:
        return Discipline.SL
    if "GS" in t:
        return Discipline.GS
    if "SG" in t:
        return Discipline.SG
    if "DH" in t:
        return Discipline.DH
    if "SX" in t or "PARALLEL" in t or "PARAL" in t:
        # usiamo AC come "speciale/variazione"
        try:
            return Discipline.AC
        except Exception:
            return Discipline.GS

    # fallback ragionevole
    return Discipline.GS


# ---------------------------------------------------------------------------
# FIS PROVIDER — NEVEITALIA (BASE, SENZA FILTRO MESE/CAT)
# ---------------------------------------------------------------------------

class FISCalendarProvider:
    """
    Scraping da NeveItalia:
    - Maschile: https://www.neveitalia.it/sport/scialpino/calendario
    - Femminile: https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile

    L’HTML può cambiare, quindi:
    - cerchiamo le tabelle che hanno una header row con "Data" e "Località"
    - poi individuiamo le colonne "Data", "Località", "Disciplina/Gara", "Evento" in modo dinamico
    """

    BASE_URLS = [
        "https://www.neveitalia.it/sport/scialpino/calendario",
        "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile",
    ]

    UA = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36 Telemark-Wax-Tune/4.0"
        )
    }

    def _fetch(self, url: str) -> str:
        r = requests.get(url, headers=self.UA, timeout=20)
        r.raise_for_status()
        return r.text

    # ---- parsing tabella calendario ----

    def _parse_calendar_table(self, table) -> List[RaceEvent]:
        """
        Prova a estrarre eventi da una singola <table>.
        Ritorna una lista di RaceEvent se la tabella assomiglia a un calendario FIS,
        altrimenti una lista vuota.
        """

        # header row (th o td)
        header_row = table.find("tr")
        if not header_row:
            return []

        header_cells = header_row.find_all(["th", "td"])
        if not header_cells:
            return []

        headers_norm = [_normalize_text(h.get_text()) for h in header_cells]

        # dobbiamo avere almeno una colonna "DATA" e una "LOCALITA'"
        if not any("DATA" in h for h in headers_norm):
            return []
        if not any("LOCALITA" in h for h in headers_norm):
            return []

        # mappa colonna -> indice
        col_idx: Dict[str, int] = {}
        for idx, h in enumerate(headers_norm):
            if "DATA" in h and "DATA" not in col_idx:
                col_idx["date"] = idx
            if "LOCALITA" in h and "place" not in col_idx:
                col_idx["place"] = idx
            if any(key in h for key in ("GARA", "DISCIPLINA", "SPECIAL", "PROVA")) and "disc" not in col_idx:
                col_idx["disc"] = idx
            if any(key in h for key in ("EVENTO", "DENOMINAZIONE", "COMPETIZIONE", "TITOLO")) and "name" not in col_idx:
                col_idx["name"] = idx
            if "NAZIONE" in h and "nation" not in col_idx:
                col_idx["nation"] = idx

        # Data e Località sono obbligatorie
        if "date" not in col_idx or "place" not in col_idx:
            return []

        events: List[RaceEvent] = []

        # righe dati (tutti i tr successivi)
        for row in header_row.find_next_siblings("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            # se non abbiamo abbastanza colonne per data/località, skip
            if len(cells) <= max(col_idx.values()):
                continue

            try:
                raw_date = cells[col_idx["date"]].get_text(strip=True)
                dt = _parse_date_it(raw_date)
                if not dt:
                    continue

                place = cells[col_idx["place"]].get_text(strip=True)

                disc_txt = ""
                if "disc" in col_idx and col_idx["disc"] < len(cells):
                    disc_txt = cells[col_idx["disc"]].get_text(strip=True)

                name = ""
                if "name" in col_idx and col_idx["name"] < len(cells):
                    name = cells[col_idx["name"]].get_text(strip=True)

                nation = None
                if "nation" in col_idx and col_idx["nation"] < len(cells):
                    n_txt = cells[col_idx["nation"]].get_text(strip=True)
                    nation = n_txt or None

                # fallback ragionevoli
                if not name:
                    # se manca un nome "ufficiale", costruiamo qualcosa di leggibile
                    name = f"Coppa del Mondo {disc_txt or ''}".strip()

                ev = RaceEvent(
                    federation=Federation.FIS,
                    codex=None,
                    name=name,
                    place=place,
                    discipline=_map_discipline(disc_txt),
                    start_date=dt,
                    end_date=dt,
                    nation=nation,
                    region=None,
                    category=None,
                    raw_type="FIS",
                    level="WC",
                )
                events.append(ev)
            except Exception:
                # se una riga fa casino, andiamo avanti
                continue

        return events

    def _parse(self, html: str) -> List[RaceEvent]:
        soup = BeautifulSoup(html, "html.parser")
        events: List[RaceEvent] = []

        # cerchiamo tutte le tabelle e teniamo solo quelle che sembrano un calendario
        for table in soup.find_all("table"):
            evs = self._parse_calendar_table(table)
            if evs:
                events.extend(evs)

        return events

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
        month: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[RaceEvent]:
        # per ora ignoriamo month/category su FIS (filtriamo solo stagione + disciplina)
        all_events: List[RaceEvent] = []

        for url in self.BASE_URLS:
            try:
                html = self._fetch(url)
                all_events.extend(self._parse(html))
            except Exception:
                # se uno dei due URL fallisce (403, ecc.), ignoriamo e andiamo avanti
                continue

        # filtro stagione: per esempio season=2025 => includi 2025-2026
        filtered: List[RaceEvent] = []
        for ev in all_events:
            y = ev.start_date.year
            if y not in (season, season + 1):
                continue
            filtered.append(ev)

        if discipline_filter:
            code = discipline_filter.upper()
            filtered = [
                ev
                for ev in filtered
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        if nation_filter:
            nf = nation_filter.upper()
            filtered = [
                ev
                for ev in filtered
                if (ev.nation or "").upper() == nf
            ]

        # region_filter non lo usiamo (per ora NeveItalia non ha regioni strutturate)

        return filtered


# ---------------------------------------------------------------------------
# ASIVA PROVIDER — DATI CODIFICATI (ESTRATTO)
# ---------------------------------------------------------------------------

# struttura compattata:
# codex, data_str, tipo, spec, category (Partec.), place, name
_ASIVA_RAW_EVENTS: List[Tuple[str, str, str, str, str, str, str]] = [
    # ---------------- DECEMBRE 2025 ----------------
    ("ITA5827", "9 dic 2025", "FIS_NJR", "GS", "F", "Courmayeur", "Trofeo ODL"),
    ("ITA0857", "9 dic 2025", "FIS_NJR", "GS", "M", "Courmayeur", "Trofeo ODL"),
    ("ITA5829", "10 dic 2025", "FIS_NJR", "GS", "F", "Courmayeur", "Trofeo ODL"),
    ("ITA0859", "10 dic 2025", "FIS_NJR", "GS", "M", "Courmayeur", "Trofeo ODL"),

    ("AA0001", "16 dic 2025", "PM_REG", "GS", "A_M", "Pila - Gressan", "Top 50"),
    ("AA0002", "16 dic 2025", "PM_REG", "GS", "A_F", "Pila - Gressan", "Top 50"),
    ("AA0003", "16 dic 2025", "PM_REG", "SL", "R_M", "Pila - Gressan", "Top 50"),
    ("AA0004", "16 dic 2025", "PM_REG", "SL", "R_F", "Pila - Gressan", "Top 50"),
    ("AA0005", "17 dic 2025", "PM_REG", "SL", "A_M", "Pila - Gressan", "Top 50"),
    ("AA0006", "17 dic 2025", "PM_REG", "SL", "A_F", "Pila - Gressan", "Top 50"),
    ("AA0007", "17 dic 2025", "PM_REG", "GS", "R_M", "Pila - Gressan", "Top 50"),
    ("AA0008", "17 dic 2025", "PM_REG", "GS", "R_F", "Pila - Gressan", "Top 50"),

    ("XA0184", "19 dic 2025", "PM_NAZ", "GS", "R_M", "Pila - Gressan", "Trofeo Coni"),
    ("XA0185", "19 dic 2025", "PM_NAZ", "GS", "R_F", "Pila - Gressan", "Trofeo Coni"),
    ("XA0186", "20 dic 2025", "PM_NAZ", "SL", "R_M", "Pila - Gressan", "Trofeo Coni"),
    ("XA0187", "20 dic 2025", "PM_NAZ", "SL", "R_F", "Pila - Gressan", "Trofeo Coni"),

    ("ITA5851", "20 dic 2025", "FIS_NJR", "SL", "F", "La Thuile", "Memorial Menel"),
    ("ITA0883", "20 dic 2025", "FIS_NJR", "SL", "M", "La Thuile", "Memorial Menel"),
    ("ITA5855", "21 dic 2025", "FIS_NJR", "SL", "F", "La Thuile", "Memorial Menel"),
    ("ITA0887", "21 dic 2025", "FIS_NJR", "SL", "M", "La Thuile", "Memorial Menel"),

    ("AA0011", "22 dic 2025", "RI_CHI_C", "SL", "A_M", "La Thuile", "Memorial Edoardo Camardella"),
    ("AA0012", "22 dic 2025", "RI_CHI_C", "SL", "A_F", "La Thuile", "Memorial Edoardo Camardella"),

    ("ITA5858", "22 dic 2025", "FIS", "GS", "F", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA0890", "22 dic 2025", "FIS", "GS", "M", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA5862", "23 dic 2025", "FIS", "GS", "F", "Frachey - Ayas", "Trofeo Pulverit"),
    ("ITA0894", "23 dic 2025", "FIS", "GS", "M", "Frachey - Ayas", "Trofeo Pulverit"),

    ("AA0009", "21 dic 2025", "CHI_FL", "SL (3 manche)", "A_M", "Valtournenche",
     "Trofeo Igor Gorgonzola Flipper"),
    ("AA0010", "21 dic 2025", "CHI_FL", "SL (3 manche)", "A_F", "Valtournenche",
     "Trofeo Igor Gorgonzola Flipper"),

    ("AA0015", "23 dic 2025", "G_MAS GSG", "GS", "GSM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0020", "23 dic 2025", "G_MAS GSG", "GS", "GSM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0017", "23 dic 2025", "G_MAS GSG", "GS", "MAM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0022", "23 dic 2025", "G_MAS GSG", "GS", "MAM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0018", "23 dic 2025", "G_MAS GSG", "GS", "MBM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0023", "23 dic 2025", "G_MAS GSG", "GS", "MBM", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0016", "23 dic 2025", "G_MAS GSG", "GS", "GSF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0021", "23 dic 2025", "G_MAS GSG", "GS", "GSF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0019", "23 dic 2025", "G_MAS GSG", "GS", "MCF", "Torgnon", "Trofeo Sci Club Torgnon"),
    ("AA0024", "23 dic 2025", "G_MAS GSG", "GS", "MCF", "Torgnon", "Trofeo Sci Club Torgnon"),

    # ---------------- GENNAIO 2026 (estratto) ----------------
    ("AA0033", "10 gen 2026", "PUL_FL", "SL (3 manche)", "P1_M", "Frachey - Ayas",
     "Trofeo Casadei Flipper"),
    ("AA0034", "10 gen 2026", "PUL_FL", "SL (3 manche)", "P1_F", "Frachey - Ayas",
     "Trofeo Casadei Flipper"),
    ("AA0035", "11 gen 2026", "PUL_FL", "SL (3 manche)", "P2_M", "Frachey - Ayas",
     "Trofeo Casadei Flipper"),
    ("AA0036", "11 gen 2026", "PUL_FL", "SL (3 manche)", "P2_F", "Frachey - Ayas",
     "Trofeo Casadei Flipper"),

    ("ITA5879", "10 gen 2026", "FIS_NJR", "GS", "F", "Pila - Gressan", "Trofeo Asto"),
    ("ITA0911", "10 gen 2026", "FIS_NJR", "GS", "M", "Pila - Gressan", "Trofeo Asto"),
    ("ITA5883", "11 gen 2026", "FIS_NJR", "GS", "F", "Pila - Gressan", "Trofeo Asto"),
    ("ITA0915", "11 gen 2026", "FIS_NJR", "GS", "M", "Pila - Gressan", "Trofeo Asto"),

    # Gressoney - La Trinité
    ("AA0031", "10 gen 2026", "RQ_CHI", "SL", "A_M", "Gressoney - La - Trinité", "Trofeo Bergland"),
    ("AA0032", "10 gen 2026", "RQ_CHI", "SL", "A_F", "Gressoney - La - Trinité", "Trofeo Bergland"),
    ("AA0037", "11 gen 2026", "RQ_CHI", "GS", "A_M", "Gressoney - La - Trinité", "Trofeo Poggi"),
    ("AA0038", "11 gen 2026", "RQ_CHI", "GS", "A_F", "Gressoney - La - Trinité", "Trofeo Poggi"),

    # Crevacol (master GS, 17 gen)
    ("AA0041", "17 gen 2026", "G_MAS GSG", "GS", "GSM", "Crevacol", "Trofeo Mima"),
    ("AA0046", "17 gen 2026", "G_MAS GSG", "GS", "GSM", "Crevacol", "Trofeo Mima"),
    ("AA0043", "17 gen 2026", "G_MAS GSG", "GS", "MAM", "Crevacol", "Trofeo Mima"),
    ("AA0048", "17 gen 2026", "G_MAS GSG", "GS", "MAM", "Crevacol", "Trofeo Mima"),
    ("AA0044", "17 gen 2026", "G_MAS GSG", "GS", "MBM", "Crevacol", "Trofeo Mima"),
    ("AA0049", "17 gen 2026", "G_MAS GSG", "GS", "MBM", "Crevacol", "Trofeo Mima"),
    ("AA0042", "17 gen 2026", "G_MAS GSG", "GS", "GSF", "Crevacol", "Trofeo Mima"),
    ("AA0047", "17 gen 2026", "G_MAS GSG", "GS", "GSF", "Crevacol", "Trofeo Mima"),
    ("AA0045", "17 gen 2026", "G_MAS GSG", "GS", "MCF", "Crevacol", "Trofeo Mima"),
    ("AA0050", "17 gen 2026", "G_MAS GSG", "GS", "MCF", "Crevacol", "Trofeo Mima"),

    # ---------------- FEBBRAIO 2026 (estratto) ----------------
    ("AA0089", "8 feb 2026", "PI_PUL", "GS", "U1_M", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),
    ("AA0090", "8 feb 2026", "PI_PUL", "GS", "U1_F", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),
    ("AA0091", "8 feb 2026", "CR_PUL", "GS", "U2_M", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),
    ("AA0092", "8 feb 2026", "CR_PUL", "GS", "U2_F", "Breuil Cervinia",
     "Trofeo Team System Trofeo Pinocchio"),

    ("ITA5942", "2 feb 2026", "FIS", "GS", "F", "Gressoney - Saint - Jean",
     "Coppa Comune di Gressoney Saint Jean"),
    ("ITA0974", "2 feb 2026", "FIS", "GS", "M", "Gressoney - Saint - Jean",
     "Coppa Comune di Gressoney Saint Jean"),

    ("ITA5953", "5 feb 2026", "FIS", "SL", "F", "Valgrisenche", "Trofeo MP Filtri"),
    ("ITA0985", "5 feb 2026", "FIS", "SL", "M", "Valgrisenche", "Trofeo MP Filtri"),

    # Pila – esempi misti febbraio
    ("AA0155", "28 feb 2026", "PUL_GG", "GS (2 manche)", "P1_M", "Pila - Gressan",
     "Coppa Comune di Gressan Gran Gigante"),
    ("AA0156", "28 feb 2026", "PUL_GG", "GS (2 manche)", "P1_F", "Pila - Gressan",
     "Coppa Comune di Gressan Gran Gigante"),

    # ---------------- MARZO 2026 (estratto) ----------------
    ("AA0203", "14 mar 2026", "PUL_GG", "GS (2 manche)", "U1_M", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),
    ("AA0204", "14 mar 2026", "PUL_GG", "GS (2 manche)", "U1_F", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),
    ("AA0205", "15 mar 2026", "PUL_GG", "GS (2 manche)", "U2_M", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),
    ("AA0206", "15 mar 2026", "PUL_GG", "GS (2 manche)", "U2_F", "Antagnod - Ayas",
     "Trofeo Telemark Ski & Bike Hire Gran Gigante"),

    ("AA0185", "8 mar 2026", "PM_REG", "GS", "A_M", "Breuil Cervinia",
     "Trofeo Azzurri del Cervino"),
    ("AA0186", "8 mar 2026", "PM_REG", "GS", "A_F", "Breuil Cervinia",
     "Trofeo Azzurri del Cervino"),

    # Pila – Caldarelli Assicurazioni (master)
    ("AA0175", "8 mar 2026", "G_MAS GSG", "GS", "GSM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0180", "8 mar 2026", "G_MAS GSG", "GS", "GSM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0177", "8 mar 2026", "G_MAS GSG", "GS", "MAM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0182", "8 mar 2026", "G_MAS GSG", "GS", "MAM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0178", "8 mar 2026", "G_MAS GSG", "GS", "MBM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0183", "8 mar 2026", "G_MAS GSG", "GS", "MBM", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0176", "8 mar 2026", "G_MAS GSG", "GS", "GSF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0181", "8 mar 2026", "G_MAS GSG", "GS", "GSF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0179", "8 mar 2026", "G_MAS GSG", "GS", "MCF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),
    ("AA0184", "8 mar 2026", "G_MAS GSG", "GS", "MCF", "Pila - Gressan",
     "Trofeo Caldarelli Assicurazioni"),

    # ---------------- APRILE 2026 (estratto – Campionati ITA + Valtournenche) ----------------
    ("XA0148", "8 apr 2026", "CI_ALL", "GS", "A_M", "Pila - Gressan",
     "Campionati Italiani Allievi"),
    ("XA0149", "8 apr 2026", "CI_ALL", "GS", "A_F", "Pila - Gressan",
     "Campionati Italiani Allievi"),
    ("XA0150", "8 apr 2026", "CI_RAG", "SL", "R_M", "Pila - Gressan",
     "Campionati Italiani Ragazzi"),
    ("XA0151", "8 apr 2026", "CI_RAG", "SL", "R_F", "Pila - Gressan",
     "Campionati Italiani Ragazzi"),

    ("XA0160", "12 apr 2026", "CI_ALL", "SL", "A_M", "Pila - Gressan",
     "Campionati Italiani Allievi"),
    ("XA0161", "12 apr 2026", "CI_ALL", "SL", "A_F", "Pila - Gressan",
     "Campionati Italiani Allievi"),
    ("XA0162", "12 apr 2026", "CI_RAG", "SX", "R_M", "Pila - Gressan",
     "Campionati Italiani Ragazzi"),
    ("XA0163", "12 apr 2026", "CI_RAG", "SX", "R_F", "Pila - Gressan",
     "Campionati Italiani Ragazzi"),

    ("AA0243", "11 apr 2026", "PI_PUL", "GS", "P1_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0244", "11 apr 2026", "PI_PUL", "GS", "P1_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0245", "11 apr 2026", "PI_PUL", "GS", "P2_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),
    ("AA0246", "11 apr 2026", "PI_PUL", "GS", "P2_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Baby"),

    ("AA0247", "12 apr 2026", "PM_PRO", "GS", "U1_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0248", "12 apr 2026", "PM_PRO", "GS", "U1_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0249", "12 apr 2026", "PI_PUL", "GS", "U2_M", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),
    ("AA0250", "12 apr 2026", "PI_PUL", "GS", "U2_F", "Valtournenche",
     "Trofeo Fondation Pro Montagna Finale Regionale Cuccioli"),

    ("ITA6087", "15 apr 2026", "FIS", "SL", "F", "Valtournenche",
     "Trofeo Comune di Valtournenche"),
    ("ITA1117", "15 apr 2026", "FIS", "SL", "M", "Valtournenche",
     "Trofeo Comune di Valtournenche"),
    ("ITA6088", "16 apr 2026", "FIS", "SL", "F", "Valtournenche",
     "Trofeo Comune di Valtournenche"),
    ("ITA1118", "16 apr 2026", "FIS", "SL", "M", "Valtournenche",
     "Trofeo Comune di Valtournenche"),

    ("ITA6089", "17 apr 2026", "FIS", "GS", "F", "Frachey - Ayas",
     "Coppa Sci Club Val d'Ayas"),
    ("ITA1119", "17 apr 2026", "FIS", "GS", "M", "Frachey - Ayas",
     "Coppa Sci Club Val d'Ayas"),
    ("ITA6090", "18 apr 2026", "FIS", "GS", "F", "Frachey - Ayas",
     "Coppa Sci Club Val d'Ayas"),
    ("ITA1120", "18 apr 2026", "FIS", "GS", "M", "Frachey - Ayas",
     "Coppa Sci Club Val d'Ayas"),
]

# set di categorie ASIVA (Partec) per il menu a tendina
ASIVA_PARTEC_CODES: List[str] = sorted(
    {cat for (_, _, _, _, cat, _, _) in _ASIVA_RAW_EVENTS if cat and cat.strip()}
)


class ASIVACalendarProvider:
    """Calendario ASIVA codificato a mano, con filtri per mese e categoria."""

    def __init__(self) -> None:
        self._cache: Dict[int, List[RaceEvent]] = {}

    def _build_for_season(self, season: int) -> List[RaceEvent]:
        if season in self._cache:
            return self._cache[season]

        events: List[RaceEvent] = []

        for codex, date_raw, tipo, spec, category, place, name in _ASIVA_RAW_EVENTS:
            dt = _parse_date_it(date_raw)
            if not dt:
                continue

            # stagione tipo 2025–26: includo dicembre 2025 + gennaio–aprile 2026
            if dt.year not in (season, season + 1):
                continue

            ev = RaceEvent(
                federation=Federation.ASIVA,
                codex=None if codex == "N.D." else codex,
                name=name,
                place=place,
                discipline=_map_discipline(spec),
                start_date=dt,
                end_date=dt,
                nation="ITA",
                region="Valle d'Aosta",
                category=category,
                raw_type=tipo,
                level="REG",
            )
            events.append(ev)

        events.sort(key=lambda e: (e.start_date, e.place, e.name))
        self._cache[season] = events
        return events

    def list_events(
        self,
        season: int,
        discipline_filter: Optional[str] = None,
        nation_filter: Optional[str] = None,
        region_filter: Optional[str] = None,
        month: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[RaceEvent]:
        events = self._build_for_season(season)

        if discipline_filter:
            code = discipline_filter.upper()
            events = [
                ev
                for ev in events
                if ev.discipline and ev.discipline.value.upper() == code
            ]

        if month is not None:
            events = [ev for ev in events if ev.start_date.month == month]

        if category:
            cat = category.upper()
            events = [
                ev
                for ev in events
                if ev.category and ev.category.upper() == cat
            ]

        # filtri nation/region per future estensioni
        if nation_filter:
            nf = nation_filter.upper()
            events = [
                ev
                for ev in events
                if (ev.nation or "").upper() == nf
            ]

        if region_filter:
            rf = region_filter.lower()
            events = [
                ev
                for ev in events
                if (ev.region or "").lower() == rf
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

        if federation is None or federation == Federation.FIS:
            try:
                events.extend(
                    self._fis.list_events(
                        season=season,
                        discipline_filter=discipline,
                        nation_filter=nation,
                        region_filter=region,
                        month=month,
                        category=category,
                    )
                )
            except Exception:
                pass

        if federation is None or federation == Federation.ASIVA:
            try:
                events.extend(
                    self._asiva.list_events(
                        season=season,
                        discipline_filter=discipline,
                        nation_filter=nation,
                        region_filter=region,
                        month=month,
                        category=category,
                    )
                )
            except Exception:
                pass

        events.sort(key=lambda ev: (ev.start_date, ev.name))
        return events
