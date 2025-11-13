# core/search.py
# Ricerca località globale snella (Nominatim + Photon)

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
NOMINATIM_EMAIL = st.secrets.get("NOMINATIM_EMAIL", None)

HEADERS_NOM = {
    "User-Agent": BASE_UA,
    "Accept": "application/json",
    "Accept-Language": "it,en;q=0.8",
    "Referer": "https://telemarkskihire.com",
}
if NOMINATIM_EMAIL:
    HEADERS_NOM["From"] = NOMINATIM_EMAIL


def _retry(func, attempts=2, delay=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(delay * (1.5 ** i))


def _concise_label(addr: dict, fallback: str) -> str:
    """Riduce display_name → 'località, regione'."""
    name = (
        addr.get("neighbourhood")
        or addr.get("hamlet")
        or addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or fallback
    )
    admin = addr.get("state") or addr.get("region") or addr.get("county") or ""
    return ", ".join([p for p in [name, admin] if p])


# -------------------- Search providers --------------------

def _search_nominatim(q: str):
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = _retry(lambda: requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q,
                "format": "json",
                "limit": 10,
                "addressdetails": 1
            },
            headers=HEADERS_NOM,
            timeout=7
        ))
        r.raise_for_status()
        js = r.json() or []
    except Exception:
        return []

    out = []
    for it in js:
        addr = it.get("address", {}) or {}
        display = _concise_label(addr, it.get("display_name", ""))
        cc = (addr.get("country_code") or "").upper()
        label = f"{_flag(cc)}  {display}" if cc else display
        lat = float(it.get("lat", 0.0))
        lon = float(it.get("lon", 0.0))
        key = f"{label}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": lat, "lon": lon, "label": label}))
    return out


def _search_photon(q: str):
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = _retry(lambda: requests.get(
            "https://photon.komoot.io/api",
            params={"q": q, "limit": 10, "lang": "it"},
            headers={"User-Agent": BASE_UA},
            timeout=7
        ))
        r.raise_for_status()
        feats = (r.json() or {}).get("features", []) or []
    except Exception:
        return []

    out = []
    for f in feats:
        props = f.get("properties", {}) or {}
        cc = (props.get("countrycode") or "").upper()
        name = props.get("name") or props.get("city") or props.get("state") or ""
        admin = props.get("state") or props.get("county") or ""
        disp = ", ".join([p for p in [name, admin] if p])

        geom = f.get("geometry", {}) or {}
        lon, lat = geom.get("coordinates", [None, None])
        if lat is None or lon is None:
            continue

        label = f"{_flag(cc)}  {disp}"
        key = f"{label}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": float(lat), "lon": float(lon), "label": label}))
    return out


# -------------------- Searchbox wrapper --------------------

def _search_function(q: str):
    """Usato da st_searchbox."""
    q = (q or "").strip()
    st.session_state["_options"] = {}

    if len(q) < 2:
        return []

    res = _search_nominatim(q)
    if not res:
        res = _search_photon(q)

    keys = []
    for key, payload in res:
        st.session_state["_options"][key] = payload
        keys.append(key)
    return keys


# -------------------- Public API --------------------

def location_searchbox(T, key="place"):
    """Ritorna sempre (lat, lon, label)."""
    selected = st_searchbox(
        search_function=_search_function,
        key=key,
        placeholder=T["search_ph"],
        clear_on_submit=False,
        debounce=350
    )

    # valori persistiti
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
