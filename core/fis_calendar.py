# core/fis_calendar.py
"""
Integrazione calendario Coppa del Mondo FIS (sito ufficiale fis-ski.com)

Legge la pagina:
  https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html

Usa i parametri:
  sectorcode=AL           -> Sci alpino
  seasoncode=YYYY         -> anno finale stagione (es. 2026 per stagione 2025/26)
  categorycode=WC         -> Coppa del Mondo
  gendercode=M/W (opz.)   -> uomini / donne

Ritorna una lista di dict, uno per ogni gara (discipline “esplose” se 2xSL ecc).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal, List, Dict, Any

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode

FIS_BASE_URL = "https://www.fis-ski.com/DB/alpine-skiing/calendar-results.html"

DISC_CODES = {"DH", "SL", "GS", "SG", "AC", "SC", "PAR", "PSL", "PGS"}


def _extract_disciplines(text: str) -> List[str]:
    """
    Estrae le sigle di disciplina (DH, SL, GS, SG, …) da stringhe tipo:
      'WC GS', 'TRA • WC 3xDH SG', 'WC 2xSL 2xGS'
    """
    return list(dict.fromkeys(re.findall(r"\b(DH|SL|GS|SG|AC|SC|PAR|PSL|PGS)\b", text)))


def _extract_genders(text: str) -> List[str]:
    """
    Colonna finale FIS:
      'W', 'M', 'W M' …
    """
    genders: List[str] = []
    if "W" in text:
        genders.append("W")
    if "M" in text:
        genders.append("M")
    return genders or ["?"]


@lru_cache(maxsize=32)
def fetch_fis_wc_races(
    season_start: int,
    gender: Literal["M", "W", "both"] = "both",
) -> List[Dict[str, Any]]:
    """
    Legge il calendario di Coppa del Mondo FIS per una stagione.

    :param season_start: anno di inizio stagione (es. 2025 per 2025/26)
    :param gender: 'M', 'W' oppure 'both'
    :return: lista di dict con chiavi:
             - date (str, come da sito FIS es. '28-29 Oct 2025')
             - place (str)
             - nation (str, es. 'ITA')
             - discipline (str: SL/GS/DH/SG/…)
             - genders (list[str]: ['M'], ['W'] o ['M','W'])
             - description (str, es. 'WC 2xSL 2xGS')
             - source (sempre 'fis')
    """
    # FIS usa l'anno FINALE della stagione come seasoncode
    seasoncode = str(season_start + 1)

    params = {
        "sectorcode": "AL",
        "seasoncode": seasoncode,
        "categorycode": "WC",
    }

    if gender == "M":
        params["gendercode"] = "M"
    elif gender == "W":
        params["gendercode"] = "W"
    # 'both' -> niente gendercode, prende tutti

    url = f"{FIS_BASE_URL}?{urlencode(params)}"

    resp = requests.get(url, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Troviamo la tabella che contiene la riga con "Status / Date / Place ..."
    table = None
    for a in soup.find_all("a"):
        if a.get_text(strip=True) == "D P C C":
            tr = a.find_parent("tr")
            if tr is not None:
                table = tr.parent
            break

    if table is None:
        # fallback: nessuna tabella trovata
        return []

    rows_data = []
    for tr in table.find_all("tr")[1:]:  # salta header
        cols = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        # ci aspettiamo ~10 colonne
        if len(cols) < 10:
            continue

        # struttura tipica:
        # 0: 'D P C C'
        # 1: date           es. '28-29 Oct 2025'
        # 2: 'Soelden WC GS'
        # 3: place          es. 'Soelden'
        # 4: place ripetuto
        # 5: nation         es. 'AUT'
        # 6: 'AL'
        # 7: 'WC GS' / 'TRA • WC 3xDH SG' ecc
        # 8: 'AL W' o 'AL W M'
        # 9: 'W' / 'M' / 'W M'
        date_str = cols[1]
        place = cols[3]
        nation = cols[5]
        cat_event = cols[7]
        gender_col = cols[9]

        rows_data.append((date_str, place, nation, cat_event, gender_col))

    events: List[Dict[str, Any]] = []

    for date_str, place, nation, cat_event, gender_col in rows_data:
        disc_list = _extract_disciplines(cat_event)
        genders = _extract_genders(gender_col)

        # Se nessuna disciplina riconosciuta, trattiamo come "ALL"
        if not disc_list:
            disc_list = ["ALL"]

        # Esplodiamo le discipline: se '2xSL 2xGS' -> un evento per SL, uno per GS
        for disc in disc_list:
            events.append(
                {
                    "date": date_str,
                    "place": place,
                    "nation": nation,
                    "discipline": disc,
                    "genders": genders,
                    "description": cat_event,
                    "source": "fis",
                }
            )

    return events


def filter_fis_wc_races(
    season_start: int,
    discipline: str | None,
    gender: Literal["M", "W", "both"] = "both",
) -> List[Dict[str, Any]]:
    """
    Wrapper comodo per la pagina Cup.

    :param discipline: 'GS', 'SL', 'DH', 'SG', oppure None/'Tutte'
    """
    if not discipline or discipline.upper() in {"ALL", "TUTTE"}:
        discipline_filter = None
    else:
        discipline_filter = discipline.upper()

    races = fetch_fis_wc_races(season_start, gender=gender)

    if discipline_filter is None:
        return races

    filtered = [
        r for r in races if r["discipline"] == discipline_filter
    ]

    return filtered
