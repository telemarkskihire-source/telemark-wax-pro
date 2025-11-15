# core/fis_calendar.py
# Lettura calendario Coppa del Mondo FIS direttamente dal DB FIS

import re
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

FIS_CALENDAR_URL = "https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html"

HEADERS = {
    "User-Agent": "TelemarkWax/1.0 (+https://telemarkskihire.com)",
    "Accept-Language": "en",
}


def _infer_discipline(event_str: str) -> Optional[str]:
    """
    Deduce la disciplina FIS standard (SL, GS, SG, DH, AC)
    dalla stringa di descrizione dell'evento (es. 'WC 2xSL', 'WC DH SG').
    """
    if not event_str:
        return None

    s = event_str.upper()

    # Alpine Combined
    if "AC" in s or "ALPINE COMBINED" in s or "COMBINED" in s:
        return "AC"

    # Downhill
    if "DH" in s or "DOWNHILL" in s:
        return "DH"

    # Super-G
    if "SG" in s or "SUPER-G" in s or "SUPER G" in s:
        return "SG"

    # Giant Slalom
    if "GS" in s or "GIANT" in s:
        return "GS"

    # Slalom (incluso 2xSL, ecc.; PSL lo trattiamo comunque come SL)
    if "SL" in s:
        return "SL"

    return None


def _gender_code(label: str) -> Optional[str]:
    """
    Converte 'Men', 'Ladies', ecc. in 'M' / 'W'.
    """
    if not label:
        return None

    t = label.strip().lower()
    if any(k in t for k in ["men", "uomini", "hommes", "männer"]):
        return "M"
    if any(k in t for k in ["ladies", "women", "donne", "damen"]):
        return "W"
    return None


def get_fis_calendar(
    season: int,
    discipline: Optional[str] = None,
    gender: Optional[str] = None,
) -> List[Dict]:
    """
    Scarica il calendario di Coppa del Mondo (WC) direttamente dal sito FIS DB.

    Args:
        season: anno di inizio stagione (es. 2025 per 2025/26)
        discipline: codice disciplina ("SL","GS","SG","DH","AC") oppure None per tutte
        gender: "M", "W" oppure None per entrambi

    Returns:
        Lista di dict con chiavi:
        - date: stringa data (come mostrata da FIS, es. '26-27 Oct 2025')
        - place: località
        - nation: codice nazione (AUT, ITA, ...)
        - event: descrizione evento FIS (es. 'WC 2xSL')
        - gender: 'M' o 'W'
    """
    # Parametri usati dal DB FIS per filtrare il calendario
    params = {
        "eventselection": "",
        "place": "",
        "sectorcode": "AL",          # Alpine
        "seasoncode": str(season),   # stagione (es. 2025)
        "categorycode": "WC",        # World Cup
        "disciplinecode": "",        # filtriamo lato client
        "gendercode": "",            # filtriamo lato client
        "racedate": "",
        "racecodex": "",
        "nationcode": "",
        "seasonmonth": f"X-{season}",
        "saveselection": "",
        "seasonselection": "",
    }

    resp = requests.get(FIS_CALENDAR_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Prima tabella di calendario presente nella pagina
    table = soup.find("table")
    if not table:
        return []

    tbody = table.find("tbody") or table

    events: List[Dict] = []

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        date_text = tds[0].get_text(" ", strip=True)
        place_text = tds[1].get_text(" ", strip=True)
        nation = tds[2].get_text(" ", strip=True)
        cat_event = tds[3].get_text(" ", strip=True)
        gender_label = tds[4].get_text(" ", strip=True)

        # Dovrebbe già essere WC, ma filtriamo comunque
        if "WC" not in cat_event.upper():
            continue

        # Genere
        g_code = _gender_code(gender_label)
        if gender and g_code and g_code != gender:
            continue
        if gender and not g_code:
            # se ho chiesto M/W e non riesco a capirlo, salto
            continue

        # Disciplina (SL, GS, SG, DH, AC)
        disc_code = _infer_discipline(cat_event)
        if discipline and disc_code and disc_code != discipline:
            continue
        if discipline and not disc_code:
            # se filtro per disciplina ma non riesco a dedurla, salto
            continue

        # Data di ordinamento (se la pagina contiene un 2025-10-26, ecc.)
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", date_text)
        sort_key = m.group(1) if m else None

        events.append(
            {
                "date": date_text,
                "sort_date": sort_key,
                "place": place_text,
                "nation": nation,
                "event": cat_event,
                "gender": g_code,
            }
        )

    # Ordiniamo per data, usando sort_date se disponibile
    events.sort(key=lambda e: (e.get("sort_date") or e["date"]))
    return events
