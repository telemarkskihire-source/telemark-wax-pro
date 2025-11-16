# core/fis_calendar.py
# Calendario FIS tramite proxy Telemark (PHP)

from __future__ import annotations

import json
from typing import List, Dict, Optional

import requests
import streamlit as st


PROXY_URL = "https://telemarkskihire.com/api/fis_proxy.php"


def get_fis_calendar(
    season: int,
    discipline: Optional[str] = None,
    gender: Optional[str] = None,
) -> List[Dict]:
    """
    Ritorna una lista di gare FIS (World Cup) usando il proxy PHP sul sito Telemark.

    Ogni evento ha la forma:
    {
        "date": "2025-11-10",
        "place": "Sölden",
        "nation": "AUT",
        "event": "GS",
        "gender": "M" / "W" / None,
    }
    """

    # Normalizziamo i parametri per il proxy
    params = {
        "season": str(season),
        "discipline": discipline or "",
        "gender": gender or "",
    }

    try:
        r = requests.get(PROXY_URL, params=params, timeout=12)
        r.raise_for_status()
    except Exception as e:
        st.error(f"Errore di rete verso il proxy FIS Telemark: {e}")
        return []

    # --- PROTEZIONE contro risposte non-JSON (HTML, errori PHP, etc.) ---
    raw = r.text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Qui sappiamo che il proxy non ha restituito JSON pulito
        preview = raw[:400].replace("\n", " ")
        st.error(
            "Il proxy FIS su telemarkskihire.com non ha restituito JSON valido.\n\n"
            f"Anteprima risposta:\n\n`{preview}`"
        )
        return []

    # Da qui in poi abbiamo JSON valido
    if not isinstance(data, dict):
        st.error("Risposta inattesa dal proxy FIS (non è un oggetto JSON).")
        return []

    if not data.get("ok", False):
        # Il proxy stesso dice che qualcosa è andato storto (es. HTML rilevato)
        msg = data.get("error") or "Errore sconosciuto dal proxy FIS."
        api_url = data.get("api_url") or data.get("url_used")
        debug = f"\n\n[Fonte: {api_url}]" if api_url else ""
        st.warning(f"Proxy FIS: {msg}{debug}")
        return []

    events = data.get("events") or []
    if not isinstance(events, list):
        st.error("Formato 'events' inatteso dal proxy FIS.")
        return []

    # Normalizziamo i campi che usa l'app
    norm_events: List[Dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue

        norm_events.append(
            {
                "date": ev.get("date") or "",
                "place": ev.get("place") or "",
                "nation": ev.get("nation") or "",
                "event": ev.get("event") or "",
                "gender": ev.get("gender"),  # può essere None
            }
        )

    return norm_events
