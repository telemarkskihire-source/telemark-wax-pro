"""
get_calendar.py

Modulo per leggere il calendario di Coppa del Mondo FIS (maschile/femminile)
dal sito Neveitalia e restituire una lista di gare strutturate.

Dipendenze: solo standard library + requests.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
from dataclasses import dataclass, asdict
from html import unescape
from typing import List, Optional

import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEVEITALIA_MEN_URL = "https://www.neveitalia.it/sport/scialpino/calendario"
NEVEITALIA_WOMEN_URL = (
    "https://www.neveitalia.it/sport/scialpino/calendario/coppa-del-mondo-femminile"
)

DEFAULT_TIMEOUT = 10

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modello dati
# ---------------------------------------------------------------------------

@dataclass
class Race:
    date: str              # "YYYY-MM-DD"
    time: str              # "HH:MM" oppure "" se non presente
    location: str          # es. "Levi (FIN)"
    event: str             # es. "Slalom Maschile"
    discipline: str        # "SL", "GS", "SG", "DH", "PAR", "OTHER"
    gender: str            # "M" oppure "F"
    source: str = "neveitalia"

    # campi grezzi utili per debug o log
    raw_date: str = ""
    raw_place: str = ""
    raw_event: str = ""


# ---------------------------------------------------------------------------
# Utilità interne
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")

def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html)


def _clean_text(html_fragment: str) -> str:
    text = _strip_tags(html_fragment)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_date_time(text: str) -> tuple[str, str]:
    """
    Converte "2025-11-16 10:00" -> ("2025-11-16", "10:00")
    e "2025-10-26" -> ("2025-10-26", "")
    """
    parts = text.strip().split()
    if not parts:
        return "", ""
    date_str = parts[0]
    time_str = parts[1] if len(parts) > 1 else ""
    # validazione base (non solleva se format diverso)
    try:
        _dt.date.fromisoformat(date_str)
    except Exception:
        pass
    return date_str, time_str


def _guess_discipline(event_text: str) -> str:
    s = event_text.lower()

    if "slalom gigante" in s or "gigante" in s:
        return "GS"
    if "slalom" in s:
        return "SL"
    if "super-g" in s or "super g" in s:
        return "SG"
    if "discesa" in s:
        return "DH"
    if "parallelo" in s:
        return "PAR"
    return "OTHER"


# blocco che contiene le info di ogni gara
_AC_BLOCK_RE = re.compile(
    r'<div class="ac-q"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)

_DATE_RE = re.compile(
    r'<span class="date">\s*([^<]+?)\s*</span>',
    re.DOTALL | re.IGNORECASE,
)
_PLACE_RE = re.compile(
    r'<span class="place">(.*?)</span>',
    re.DOTALL | re.IGNORECASE,
)
_EVENT_RE = re.compile(
    r'<span class="event">\s*([^<]+?)\s*</span>',
    re.DOTALL | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Parsing Neveitalia
# ---------------------------------------------------------------------------

def _parse_neveitalia_calendar_html(html: str, gender: str) -> List[Race]:
    """
    Prende l'HTML della pagina calendario Neveitalia
    e restituisce una lista di Race NON filtrate.
    """
    gender = gender.upper()
    if gender not in {"M", "F"}:
        raise ValueError("gender deve essere 'M' oppure 'F'")

    races: List[Race] = []

    for block_match in _AC_BLOCK_RE.finditer(html):
        block = block_match.group(1)

        m_date = _DATE_RE.search(block)
        m_place = _PLACE_RE.search(block)
        m_event = _EVENT_RE.search(block)

        if not (m_date and m_place and m_event):
            # blocco non standard, lo saltiamo
            continue

        raw_date = _clean_text(m_date.group(1))
        raw_place = _clean_text(m_place.group(1))
        raw_event = _clean_text(m_event.group(1))

        date_str, time_str = _parse_date_time(raw_date)
        discipline = _guess_discipline(raw_event)

        races.append(
            Race(
                date=date_str,
                time=time_str,
                location=raw_place,
                event=raw_event,
                discipline=discipline,
                gender=gender,
                raw_date=raw_date,
                raw_place=raw_place,
                raw_event=raw_event,
            )
        )

    return races


def _fetch_neveitalia_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; TelemarkWaxApp/1.0; +https://telemarkskihire.com)"
        )
    }
    resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def get_fis_worldcup_races(
    year: int = 2025,
    gender: str = "M",
    discipline: Optional[str] = None,
) -> List[dict]:
    """
    Ritorna le gare di Coppa del Mondo FIS (via Neveitalia) per la stagione
    che inizia nell'anno `year` (es. 2025 -> stagione 2025/26).

    Parametri:
        year: anno di inizio stagione (es. 2025).
        gender: "M" per maschile, "F" per femminile.
        discipline: se None -> tutte.
                     se "SL", "GS", "SG", "DH", "PAR" -> filtra per disciplina.

    Ritorna:
        Lista di dict {date, time, location, event, discipline, gender, source, ...}
        pronta da usare nella tua app Streamlit.
    """
    gender = gender.upper()
    if gender not in {"M", "F"}:
        raise ValueError("gender deve essere 'M' oppure 'F'")

    url = NEVEITALIA_MEN_URL if gender == "M" else NEVEITALIA_WOMEN_URL

    try:
        html = _fetch_neveitalia_html(url)
    except Exception as e:
        logger.error("Errore nel download del calendario Neveitalia: %s", e)
        return []

    all_races = _parse_neveitalia_calendar_html(html, gender=gender)

    start_year = int(year)
    end_year = start_year + 1

    discipline = discipline.upper() if discipline else None

    filtered: List[dict] = []

    for r in all_races:
        # filtro stagione: anno == year o year+1
        date_obj = None
        if r.date:
            try:
                date_obj = _dt.date.fromisoformat(r.date)
            except Exception:
                pass

        if date_obj is not None:
            if not (start_year <= date_obj.year <= end_year):
                continue

        # filtro disciplina
        if discipline and r.discipline != discipline:
            continue

        filtered.append(asdict(r))

    return filtered


# ---------------------------------------------------------------------------
# Test veloce da riga di comando
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    races = get_fis_worldcup_races(year=2025, gender="M", discipline=None)
    print(f"Trovate {len(races)} gare.")
    for r in races[:5]:
        print(r)
