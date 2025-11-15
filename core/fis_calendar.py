# core/fis_calendar.py
"""
Calendario FIS tramite PROXY telemarkskihire.com/api/fis_proxy.php

Questo aggira:
 - blocchi anti-bot
 - blocchi geografici
 - redirect javascript

Dipende da "beautifulsoup4".
"""

from __future__ import annotations
import re
from typing import List, Dict, Any, Optional
import requests

from bs4 import BeautifulSoup


PROXY_URL = "https://telemarkskihire.com/api/fis_proxy.php"

DISCIPLINE_MAP = {
    "ALL": "",
    "SL": "SL",
    "GS": "GS",
    "SG": "SG",
    "DH": "DH",
    "AC": "AC",
}

GENDER_MAP = {
    "ALL": "",
    "M": "M",
    "W": "W",
}


def build_params(season: int, discipline: str, gender: str) -> Dict[str, str]:
    return {
        "categorycode": "WC",
        "disciplinecode": discipline,
        "gendercode": gender,
        "seasoncode": str(season),
        "seasonmonth": f"X-{season}",
        "sectorcode": "AL",
        "nationcode": "",
        "place": "",
        "racecodex": "",
        "eventselection": "",
        "racedate": "",
        "saveselection": "-1",
    }


def fetch_html(season: int, discipline: Optional[str], gender: Optional[str]) -> str:
    dcode = DISCIPLINE_MAP.get((discipline or "ALL").upper(), "")
    gcode = GENDER_MAP.get((gender or "ALL").upper(), "")

    params = build_params(season, dcode, gcode)

    r = requests.get(PROXY_URL, params=params, timeout=15)
    r.raise_for_status()

    return r.text


def extract_table(soup: BeautifulSoup):
    # Cerca la tabella con header contenente "Date" e "Place"
    for table in soup.find_all("table"):
        head = table.find("thead")
        if not head:
            continue
        text = head.get_text(" ", strip=True).lower()
        if "date" in text and "place" in text:
            return table
    return None


def parse_rows(table) -> List[Dict[str, Any]]:
    if not table:
        return []

    body = table.find("tbody") or table
    events = []

    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        cells = [td.get_text(" ", strip=True) for td in tds]

        # --- DATA ---
        date = ""
        for c in cells:
            if re.search(r"\d{4}", c):
                date = c
                break
        if not date:
            date = cells[0]

        # --- NAZIONE ---
        nation = ""
        for c in cells:
            if re.fullmatch(r"[A-Z]{3}", c):
                nation = c
                break

        # --- EVENTO ---
        event = ""
        for c in cells:
            if "WC" in c:
                event = c
                break
        if not event:
            continue

        # --- LOCALITÀ ---
        place = ""
        hit_date = False
        for c in cells:
            if not hit_date:
                if c == date:
                    hit_date = True
                continue
            if "WC" in c:
                continue
            if re.fullmatch(r"[A-Z]{3}", c):
                continue
            place = c
            break
        if not place:
            place = cells[1]

        # --- GENERE ---
        gender = ""
        for c in cells:
            if c in ("M", "W"):
                gender = c
                break

        events.append({
            "date": date,
            "place": place,
            "nation": nation,
            "event": event,
            "gender": gender,
            "raw": " | ".join(cells),
        })

    return events


def get_fis_calendar(season: int, discipline: Optional[str], gender: Optional[str]) -> List[Dict[str, Any]]:
    html = fetch_html(season, discipline, gender)
    soup = BeautifulSoup(html, "html.parser")
    table = extract_table(soup)
    events = parse_rows(table)
    return events
