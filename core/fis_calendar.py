# core/fis_calendar.py
# Calendario FIS (World Cup) via proxy Telemark.

from __future__ import annotations

import os
from typing import List, Dict, Optional

import requests


FIS_PROXY_URL = os.getenv(
    "FIS_PROXY_URL",
    "https://www.telemarkskihire.com/api/fis_proxy.php",
)


def _build_params(
    season: int,
    discipline: Optional[str],
    gender: Optional[str],
) -> dict:
    params: dict = {}
    if season:
        params["season"] = int(season)
    if discipline:
        params["discipline"] = discipline
    if gender:
        params["gender"] = gender
    return params


def get_fis_calendar(
    season: int,
    discipline: Optional[str] = None,
    gender: Optional[str] = None,
) -> List[Dict]:
    """
    Ritorna una lista di gare World Cup FIS.

    Ogni elemento:
        {
            "date":   "27-10-2024",
            "place":  "Sölden",
            "nation": "AUT",
            "event":  "WC GS",
            "gender": "M",
        }
    """
    params = _build_params(season, discipline, gender)

    r = requests.get(FIS_PROXY_URL, params=params, timeout=20)
    r.raise_for_status()

    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Errore proxy FIS: {data}")

    events = data.get("events", [])

    # Filtro di sicurezza lato client per stagione:
    # se nel campo "date" compare l'anno richiesto lo teniamo,
    # altrimenti teniamo tutto (fallback se formato data cambia).
    season_str = str(season)
    filtered = [ev for ev in events if season_str in str(ev.get("date", ""))]
    if filtered:
        events = filtered

    return events
