# core/search.py
"""
Ricerca località + selezione nazione per Telemark · Pro Wax & Tune.

- Usa l'API di geocoding di Open-Meteo (più veloce e stabile di Nominatim).
- Restituisce lat, lon, etichetta località e codice ISO2 della nazione.
- Gestisce la persistenza in st.session_state: 'lat', 'lon', 'place_label'.
"""

from __future__ import annotations

import math
from typing import Tuple, Dict

import requests
import streamlit as st
from streamlit_searchbox import st_searchbox


UA = {"User-Agent": "telemark-wax-pro/1.0"}

# Nazioni proposte nel select
COUNTRIES: Dict[str, str] = {
    "Italia": "IT",
    "Svizzera": "CH",
    "Francia": "FR",
    "Austria": "AT",
    "Germania": "DE",
    "Spagna": "ES",
    "Norvegia": "NO",
    "Svezia": "SE",
}


# ---------- piccoli helper ----------

def flag(cc: str) -> str:
    """Trasforma 'IT' → 🇮🇹, ecc."""
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"


def _label_from_result(res: dict) -> str:
    """
    Costruisce un'etichetta compatta a partire da una response di
    https://geocoding-api.open-meteo.com/v1/search
    """
    name = res.get("name") or ""
    admin1 = res.get("admin1") or res.get("admin2") or ""
    country = res.get("country") or ""
    parts = [p for p in [name, admin1, country] if p]
    base = ", ".join(parts) if parts else name or country or "?"
    cc = res.get("country_code") or ""
    return f"{flag(cc)}  {base}" if cc else base


# ---------- funzione passata a st_searchbox ----------

def _geo_search(q: str, iso2: str) -> list[str]:
    """Cerca località tramite Open-Meteo geocoding."""
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        params = {
            "name": q,
            "count": 12,
            "language": "it",
            "format": "json",
        }
        if iso2:
            params["country"] = iso2

        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params=params,
            headers=UA,
            timeout=6,
        )
        r.raise_for_status()
        data = r.json() or {}
        results = data.get("results") or []
    except Exception:
        return []

    # salviamo i risultati in session_state per recuperarli dopo
    opts: Dict[str, dict] = {}
    labels: list[str] = []
    for res in results:
        lat = float(res.get("latitude"))
        lon = float(res.get("longitude"))
        label = _label_from_result(res)
        key = f"{label}|||{lat:.6f},{lon:.6f}"
        opts[key] = {
            "lat": lat,
            "lon": lon,
            "label": label,
            "raw": res,
        }
        labels.append(key)

    st.session_state._geo_options = opts  # type: ignore[attr-defined]
    return labels


# ---------- entrypoint usato dalla main app ----------

def location_searchbox(T: dict) -> Tuple[float, float, str, str]:
    """
    Disegna:
      - titolo 1) Cerca...
      - select della nazione
      - searchbox con autosuggest
    e restituisce (lat, lon, place_label, iso2).

    Richiede:
      - dizionario T (traduzioni correnti) da core.i18n.L
    """

    st.markdown(f"### {T['search_title']}")

    col_search, col_country = st.columns([3, 1])

    # select della nazione
    with col_country:
        sel_country = st.selectbox(
            T["country"],
            list(COUNTRIES.keys()),
            index=0,
            key="country_sel",
        )
        iso2 = COUNTRIES[sel_country]

    # searchbox → usa _geo_search con il country filter
    with col_search:
        def _wrapper(q: str) -> list[str]:
            return _geo_search(q, iso2)

        selected = st_searchbox(
            _wrapper,
            key="place",
            placeholder=T["search_ph"],
            clear_on_submit=False,
        )

    # valori di default (Champoluc) se non abbiamo ancora nulla
    lat = float(st.session_state.get("lat", 45.83333))
    lon = float(st.session_state.get("lon", 7.73333))
    place_label = str(
        st.session_state.get(
            "place_label",
            f"{flag('IT')}  Champoluc, Valle d'Aosta — IT",
        )
    )

    # se l’utente ha scelto un elemento dalla lista
    if selected and "|||" in selected:
        opts = getattr(st.session_state, "_geo_options", {})
        info = opts.get(selected)
        if info:
            lat = float(info["lat"])
            lon = float(info["lon"])
            place_label = str(info["label"])
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = place_label

    # badge riassuntivo
    st.markdown(
        f"""
<div class='badge'>
  📍 <b>{place_label}</b> · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b>
</div>
""",
        unsafe_allow_html=True,
    )

    return lat, lon, place_label, iso2
