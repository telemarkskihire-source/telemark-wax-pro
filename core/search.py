# core/search.py
# Ricerca località con Nominatim + streamlit_searchbox

import math
from typing import Tuple

import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

UA = {
    "User-Agent": "telemark-wax-pro/1.0 (telemark-location-search)"
}

# Champoluc default
DEFAULT_LAT = 45.83333
DEFAULT_LON = 7.73333
DEFAULT_LABEL = "🇮🇹 Champoluc-Champlan, Valle d’Aosta — IT"
DEFAULT_ISO2 = "IT"


COUNTRIES = {
    "Italia": "IT",
    "Svizzera": "CH",
    "Francia": "FR",
    "Austria": "AT",
    "Germania": "DE",
    "Spagna": "ES",
    "Norvegia": "NO",
    "Svezia": "SE",
}


def flag(cc: str) -> str:
    """Converte codice paese ISO2 in bandierina Unicode."""
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"


def concise_label(addr: dict, fallback: str) -> str:
    """Etichetta compatta 'Paese, Regione'."""
    name = (
        addr.get("neighbourhood")
        or addr.get("hamlet")
        or addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or fallback
    )
    admin1 = (
        addr.get("state")
        or addr.get("region")
        or addr.get("county")
        or ""
    )
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in (name, admin1) if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s


@st.cache_data(ttl=60 * 60, show_spinner=False)
def _nominatim_api(query: str, country_iso2: str | None, limit: int = 10):
    """Chiamata Nominatim, cacheata. Se country_iso2 è None, nessun filtro paese."""
    params = {
        "q": query,
        "format": "json",
        "limit": limit,
        "addressdetails": 1,
    }
    if country_iso2:
        params["countrycodes"] = country_iso2.lower()

    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers=UA,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def location_searchbox(T) -> Tuple[float, float, str, str]:
    """
    Disegna:
      - selectbox paese
      - searchbox con suggerimenti
    Ritorna (lat, lon, label, iso2) della località selezionata
    mantenendo lo stato in sessione.
    """

    # Stato iniziale
    if "loc_lat" not in st.session_state:
        st.session_state["loc_lat"] = DEFAULT_LAT
        st.session_state["loc_lon"] = DEFAULT_LON
        st.session_state["loc_label"] = DEFAULT_LABEL
        st.session_state["loc_iso2"] = DEFAULT_ISO2

    # ----- UI: country + searchbox -----
    col_search, col_country = st.columns([2, 1])

    with col_country:
        country_name = st.selectbox(
            T["country"],
            list(COUNTRIES.keys()),
            index=list(COUNTRIES.keys()).index("Italia"),
            key="loc_country_sel",
        )
        iso2 = COUNTRIES[country_name]

    def search_fn(text: str):
        text = (text or "").strip()
        if len(text) < 3:
            # Non chiamiamo l'API per input troppo corto
            return []

        results = []
        try:
            # 1) con filtro paese
            js = _nominatim_api(text, iso2)
            # 2) fallback senza filtro se vuoto
            if not js:
                js = _nominatim_api(text, None)

            for it in js:
                lat = float(it.get("lat", 0))
                lon = float(it.get("lon", 0))
                addr = it.get("address", {}) or {}
                label_core = concise_label(addr, it.get("display_name", ""))
                cc = (addr.get("country_code") or "").upper()
                lab = f"{flag(cc)} {label_core}"
                # codifichiamo lat/lon nell'opzione
                value = f"om|{lat:.6f}|{lon:.6f}|{lab}"
                results.append(value)
        except Exception:
            # in caso di errore silenzioso, niente suggerimenti
            return []

        return results

    with col_search:
        selected = st_searchbox(
            search_fn,
            key="loc_searchbox",
            placeholder=T["search_ph"],
            clear_on_submit=False,
            default=None,
        )

    # ----- parsing selezione -----
    if selected and isinstance(selected, str) and selected.startswith("om|"):
        # formato: om|lat|lon|label
        try:
            _, slat, slon, label = selected.split("|", 3)
            st.session_state["loc_lat"] = float(slat)
            st.session_state["loc_lon"] = float(slon)
            st.session_state["loc_label"] = label
            st.session_state["loc_iso2"] = iso2
        except Exception:
            pass  # in caso di valore strano non rompiamo tutto

    lat = float(st.session_state["loc_lat"])
    lon = float(st.session_state["loc_lon"])
    label = st.session_state["loc_label"]
    iso2_sel = st.session_state["loc_iso2"]

    # piccolo hint sotto i campi
    if len((st.session_state.get("loc_searchbox") or "")) < 3:
        st.info(T["hint_min_chars"])
    else:
        st.success(T["selected_ok"])

    return lat, lon, label, iso2_sel
