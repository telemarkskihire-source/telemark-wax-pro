# core/pages/utils.py
# Utility generali per Telemark · Pro Wax & Tune
#
# Include:
#   - geocoder avanzato (open-meteo)
#   - pulizia nomi località (ASIVA/FIS)
#   - gestione ctx location & session_state
#   - helper varie

from __future__ import annotations
from typing import Optional, Dict, Any

import requests
import streamlit as st

MIN_ELEVATION_M = 1000.0
UA = {"User-Agent": "telemark-wax-pro/4.0"}


# --------------------------------------------------------------------
# 1) Sanitizzazione nomi località, gara, comprensorio
# --------------------------------------------------------------------
def clean_place_name(raw_place: str) -> str:
    """
    Rende più robusto il nome da geocodificare:
    - "Soelden (AUT)" → "Soelden"
    - "Pila - Gressan" → "Pila"
    - "La Thuile / Piccolo San Bernardo" → "La Thuile"
    """
    if not raw_place:
        return ""

    txt = raw_place.strip()

    # Taglia parentesi: es. (AUT)
    if "(" in txt:
        txt = txt.split("(")[0].strip()

    # Taglia dopo trattini multipli
    if " - " in txt:
        txt = txt.split(" - ")[0].strip()

    # Taglia dopo slash
    if "/" in txt:
        txt = txt.split("/")[0].strip()

    return txt or raw_place.strip()


# --------------------------------------------------------------------
# 2) Geocoder open-meteo robusto
# --------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def geocode_place(query: str) -> Optional[Dict[str, Any]]:
    """
    Geocoding multiplo:
    - Accetta nomi come "Pila", "Plan de Corones", "Cervinia"
    - Cerca fino a 10 risultati
    - Sceglie:
        1) il primo sopra MIN_ELEVATION_M
        2) altrimenti il più alto
    """
    q = (query or "").strip()
    if not q:
        return None

    params = {
        "name": q,
        "language": "it",
        "count": 10,
        "format": "json",
    }

    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params=params,
            headers=UA,
            timeout=8,
        )
        r.raise_for_status()
        js = r.json() or {}
    except Exception:
        return None

    results = js.get("results") or []
    if not results:
        return None

    best_high = None
    best_any = None
    best_any_elev = -9999.0

    for it in results:
        elev_val = it.get("elevation")
        try:
            elev = float(elev_val) if elev_val is not None else None
        except Exception:
            elev = None

        # 1) riferimento più alto assoluto
        if elev is not None and elev > best_any_elev:
            best_any_elev = elev
            best_any = it
        if best_any is None:
            best_any = it

        # 2) primo sopra soglia montana
        if elev is not None and elev >= MIN_ELEVATION_M and best_high is None:
            best_high = it

    chosen = best_high or best_any
    if not chosen:
        return None

    # label con bandiera
    cc = (chosen.get("country_code") or "").upper()
    flag = "".join(chr(127397 + ord(c)) for c in cc) if len(cc) == 2 else "🏳️"

    name = chosen.get("name") or ""
    admin1 = chosen.get("admin1") or chosen.get("admin2") or ""
    full_label = f"{flag}  {name}, {admin1}".replace(" ,", ",")

    return {
        "lat": float(chosen.get("latitude", 0.0)),
        "lon": float(chosen.get("longitude", 0.0)),
        "label": full_label,
    }


# --------------------------------------------------------------------
# 3) Ensure base location (fallback Champoluc)
# --------------------------------------------------------------------
def ensure_base_location(default_lat=45.8333, default_lon=7.7333) -> Dict[str, Any]:
    """
    Ritorna:
        { lat, lon, label }
    Usa quello già in session_state, oppure default Champoluc.
    """
    if "lat" in st.session_state and "lon" in st.session_state:
        return {
            "lat": st.session_state["lat"],
            "lon": st.session_state["lon"],
            "label": st.session_state.get("place_label", "Località selezionata"),
        }

    return {
        "lat": default_lat,
        "lon": default_lon,
        "label": "🇮🇹 Champoluc, Valle d’Aosta — IT"
    }


# --------------------------------------------------------------------
# 4) Centra contesto (ctx) su una località di gara o click
# --------------------------------------------------------------------
def center_ctx_on_place(ctx: Dict[str, Any], place_name: str) -> Dict[str, Any]:
    """
    Funzione generica per centrare la mappa su una località:
    - pulisce nome
    - geocoda
    - aggiorna ctx e session_state
    """
    clean_name = clean_place_name(place_name)
    geo = geocode_place(clean_name)

    if geo:
        lat = geo["lat"]
        lon = geo["lon"]
        label = geo["label"]
    else:
        # fallback: lascia coordinate attuali
        lat = ctx.get("lat", 45.8333)
        lon = ctx.get("lon", 7.7333)
        label = ctx.get("place_label", place_name)

    ctx["lat"] = lat
    ctx["lon"] = lon
    ctx["place_label"] = label

    st.session_state["lat"] = lat
    st.session_state["lon"] = lon
    st.session_state["place_label"] = label

    return ctx


# --------------------------------------------------------------------
# 5) Wrapper sicuro per session_state
# --------------------------------------------------------------------
def ss_get(key: str, default=None):
    return st.session_state.get(key, default)


def ss_set(key: str, value):
    st.session_state[key] = value


# --------------------------------------------------------------------
# 6) Utility varie
# --------------------------------------------------------------------
def nearest_row(df, target_ts):
    """
    Ritorna la riga del dataframe df più vicina al timestamp target_ts.
    """
    if df is None or df.empty:
        return None
    idx = (df["time_local"] - target_ts).abs().idxmin()
    return df.loc[idx]


def print_debug(msg: str):
    """Debug elegante in basso."""
    st.markdown(
        f"<div style='font-size:0.75rem;color:#8899aa;margin-top:0.4rem'>🔧 {msg}</div>",
        unsafe_allow_html=True,
    )
