# core/search.py
# Ricerca località usando Open-Meteo Geocoding (robusto) + fallback Photon

import time
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox


# -------------------- Helpers --------------------

def _flag(cc: str) -> str:
    try:
        cc = cc.upper()
        return chr(127397 + ord(cc[0])) + chr(127397 + ord(cc[1]))
    except Exception:
        return "🏳️"


BASE_UA = "telemark-wax-pro/1.0 (+https://telemarkskihire.com)"


def _retry(func, attempts=2, delay=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(delay * (1.5 ** i))


# -------------------- OPEN-METEO GEOCODING --------------------

def _search_openmeteo(q: str):
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = _retry(
            lambda: requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={
                    "name": q,
                    "count": 10,
                    "language": "it",
                    "format": "json",
                },
                headers={"User-Agent": BASE_UA},
                timeout=7,
            )
        )
        r.raise_for_status()
        js = r.json() or {}
        results = js.get("results") or []
    except Exception:
        return []

    out = []
    for rec in results:
        name = rec.get("name", "")
        admin1 = rec.get("admin1") or rec.get("admin2") or ""
        cc = (rec.get("country_code") or "").upper()
        pieces = [p for p in [name, admin1] if p]
        base = ", ".join(pieces) if pieces else name
        label = f"{_flag(cc)}  {base}" if cc else base
        lat = float(rec.get("latitude"))
        lon = float(rec.get("longitude"))
        key = f"{label}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": lat, "lon": lon, "label": label}))
    return out


# -------------------- PHOTON (fallback) --------------------

def _search_photon(q: str):
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = _retry(
            lambda: requests.get(
                "https://photon.komoot.io/api",
                params={"q": q, "limit": 10, "lang": "it"},
                headers={"User-Agent": BASE_UA},
                timeout=7,
            )
        )
        r.raise_for_status()
        feats = (r.json() or {}).get("features", []) or []
    except Exception:
        return []

    out = []
    for f in feats:
        props = f.get("properties", {}) or {}
        cc = (props.get("countrycode") or "").upper()
        name = props.get("name") or props.get("city") or props.get("state") or ""
        admin1 = props.get("state") or props.get("county") or ""
        disp = ", ".join([p for p in [name, admin1] if p])

        geom = f.get("geometry", {}) or {}
        lon, lat = geom.get("coordinates", [None, None])
        if lat is None or lon is None:
            continue

        label = f"{_flag(cc)}  {disp}" if disp else _flag(cc)
        key = f"{label}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": float(lat), "lon": float(lon), "label": label}))
    return out


# -------------------- Funzione usata da st_searchbox --------------------

def _search_function(q: str):
    q = (q or "").strip()
    st.session_state["_options"] = {}

    if len(q) < 2:
        return []

    # 1) Open-Meteo (più affidabile nel tuo ambiente)
    res = _search_openmeteo(q)

    # 2) Se proprio nulla, prova Photon
    if not res:
        res = _search_photon(q)

    keys = []
    for key, payload in res:
        st.session_state["_options"][key] = payload
        keys.append(key)
    return keys


# -------------------- API pubblica --------------------

def location_searchbox(T, key: str = "place"):
    """
    Mostra il searchbox e restituisce SEMPRE (lat, lon, label)
    usando i valori salvati in sessione come default.
    """
    selected = st_searchbox(
        search_function=_search_function,
        key=key,
        placeholder=T["search_ph"],
        clear_on_submit=False,
        debounce=350,
    )

    # default / persistiti
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    label = st.session_state.get("place_label", "Champoluc")

    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state["_options"].get(selected)
        if info:
            lat = float(info.get("lat", lat))
            lon = float(info.get("lon", lon))
            label = str(info.get("label", label))
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = label

    return lat, lon, label
