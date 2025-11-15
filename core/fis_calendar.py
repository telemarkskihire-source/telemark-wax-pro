# core/fis_calendar.py
"""
Integrazione calendario FIS ufficiale (alpine skiing, World Cup).

- Scarica l'HTML da fis-ski.com con i parametri corretti (season, disciplina, gender, WC).
- Effettua il parsing della tabella con BeautifulSoup.
- Ritorna una lista di dizionari Python pronti per lo Streamlit UI.

⚠️ Dipendenza: beautifulsoup4
Assicurati di avere nel tuo requirements.txt:
    beautifulsoup4
"""

from __future__ import annotations

import re
from typing import List, Optional, Dict, Any

import requests

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # messaggio chiaro se manca il pacchetto
    raise RuntimeError(
        "Per usare core.fis_calendar serve il pacchetto 'beautifulsoup4' "
        "nel requirements.txt della tua app Streamlit."
    ) from exc


BASE_URL = "https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html"


# mappa “discipline” che userai nello UI -> codice FIS per la query
DISCIPLINE_CODE_MAP: Dict[str, str] = {
    "ALL": "",    # nessun filtro disciplina
    "SL": "SL",
    "GS": "GS",
    "SG": "SG",
    "DH": "DH",
    "AC": "AC",   # Alpine Combined
    "PAR": "PAR", # Parallel / Team, se servirà
}

GENDER_CODE_MAP: Dict[str, str] = {
    "ALL": "",    # All
    "M": "M",
    "W": "W",
}


def _build_fis_params(
    season_start: int,
    discipline_code: str = "",
    gender_code: str = "",
) -> Dict[str, str]:
    """
    Costruisce il dizionario di querystring per il calendario FIS WC alpino.
    """
    season_str = str(season_start)

    params = {
        "categorycode": "WC",              # Coppa del Mondo
        "disciplinecode": discipline_code, # SL / GS / ...
        "eventselection": "",              # tutti gli eventi
        "gendercode": gender_code,         # "" / "M" / "W"
        "nationcode": "",
        "place": "",
        "racecodex": "",
        "racedate": "",
        "saveselection": "-1",
        "seasoncode": season_str,
        "seasonmonth": f"X-{season_str}",  # come visto sulla pagina FIS
        "seasonselection": "",
        "sectorcode": "AL",                # Alpine
    }
    return params


def fetch_fis_wc_html(
    season_start: int,
    discipline_code: str = "",
    gender_code: str = "",
    timeout: int = 20,
) -> str:
    """
    Scarica l'HTML del calendario FIS WC per la stagione richiesta.
    """
    params = _build_fis_params(season_start, discipline_code, gender_code)
    resp = requests.get(BASE_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_races_from_table(table_html: str) -> List[Dict[str, Any]]:
    """
    Parsing della tabella "Status / Date / Place / ... / Category & Event / Gender".

    Ritorna una lista di dict:
      {
        "date": "10-11 Dec 2025",
        "place": "Val Gardena",
        "nation": "ITA",
        "event": "WC DH",
      }
    """
    soup = BeautifulSoup(table_html, "html.parser")

    table = soup.find("table")
    if not table:
        return []

    tbody = table.find("tbody") or table

    races: List[Dict[str, Any]] = []

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        cell_texts = [td.get_text(" ", strip=True) for td in tds]
        row_text = "  ".join(cell_texts)

        # 1) Data: di solito è la seconda colonna (index 1) es: "26-27 Nov 2025"
        date_text = cell_texts[1] if len(cell_texts) > 1 else ""

        # 2) Nazione: tipicamente una stringa di 3 lettere maiuscole (ITA, SUI, AUT, ...)
        nation = ""
        for txt in cell_texts:
            if re.fullmatch(r"[A-Z]{3}", txt):
                nation = txt
                break

        # 3) Evento (Category & Event): il testo che contiene "WC"
        event = ""
        for txt in cell_texts:
            if "WC" in txt:
                event = txt
                break

        # Se non c'è "WC" saltiamo (dovrebbe già essere filtrato ma meglio essere rigidi)
        if not event:
            continue

        # 4) Place: prendiamo la prima cella “non tecnica” dopo la data
        place = ""
        for txt in cell_texts[2:]:
            # escludiamo celle evidentemente tecniche (AL, WC, codici vari)
            if "WC" in txt:
                continue
            if re.fullmatch(r"[A-Z]{3}", txt):
                # è la nazione, non il posto
                continue
            place = txt
            break

        if not place:
            # fallback
            place = cell_texts[2]

        races.append(
            {
                "date": date_text,
                "place": place,
                "nation": nation,
                "event": event,
                "row_raw": row_text,
            }
        )

    return races


def filter_fis_wc_races(
    season_start: int,
    discipline: Optional[str] = None,
    gender: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    API principale da usare nello Streamlit.

    Parameters
    ----------
    season_start : int
        Anno di inizio stagione (es. 2025 per 2025/26).
    discipline : Optional[str]
        "SL", "GS", "SG", "DH", "AC", "PAR" oppure None / "ALL".
    gender : Optional[str]
        "M", "W" oppure None / "ALL".

    Returns
    -------
    List[Dict[str, Any]]
        Lista di gare FIS WC già ripulite (date, place, nation, event).
    """
    discipline_code = DISCIPLINE_CODE_MAP.get((discipline or "ALL").upper(), "")
    gender_code = GENDER_CODE_MAP.get((gender or "ALL").upper(), "")

    html = fetch_fis_wc_html(
        season_start=season_start,
        discipline_code=discipline_code,
        gender_code=gender_code,
    )

    races = _extract_races_from_table(html)
    return races
