# core/search.py
# Ricerca località snella:
# - Nominatim + fallback Photon
# - usa country_selectbox per ISO2
# - location_searchbox mantiene lat/lon/label in session_state

import time
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# -------------------- Costanti & helpers --------------------
COUNTRIES = {
    "Italia":   "IT",
    "Svizzera": "CH",
    "Francia":  "FR",
    "Austria":  "AT",
    "Germania": "DE",
    "Spagna":   "ES",
    "Norvegia": "NO",
    "Svezia":   "SE",
}

def _flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
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


def _retry(func, attempts: int = 2, sleep: float = 0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.5 ** i))


# -------------------- UI: scelta paese --------------------
def country_selectbox(T):
    label = st.selectbox(
        T["country"],
        list(COUNTRIES.keys()),
        index=0,
        key="country_sel",
    )
    return COUNTRIES[label]


# -------------------- SEARCH: Nominatim + Photon --------------------
def _concise_label(addr: dict, fallback: str) -> str:
    name = (
        addr.get("neighbourhood")
        or addr.get("hamlet")
        or addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or fallback
    )
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    parts = [p for p in [name, admin1] if p]
    return ", ".join(parts)


def _search_nominatim(q: str, iso2: str):
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = _retry(
            lambda: requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "json",
                    "limit": 10,
                    "addressdetails": 1,
                    "countrycodes": iso2.lower(),
                },
                headers=HEADERS_NOM,
                timeout=8,
            )
        )
        r.raise_for_status()
        js = r.json() or []
    except Exception:
        return []

    out = []
    for it in js:
        addr = it.get("address", {}) or {}
        lab_core = _concise_label(addr, it.get("display_name", ""))
        cc = (addr.get("country_code") or "").upper()
        lab = f"{_flag(cc)}  {lab_core}" if cc else lab_core
        lat = float(it.get("lat", 0.0))
        lon = float(it.get("lon", 0.0))
        key = f"{lab}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": lat, "lon": lon, "label": lab, "addr": addr}))
    return out


def _search_photon(q: str, iso2: str):
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = _retry(
            lambda: requests.get(
                "https://photon.komoot.io/api",
                params={"q": q, "limit": 10, "lang": "it"},
                headers={"User-Agent": BASE_UA},
                timeout=8,
            )
        )
        r.raise_for_status()
        js = r.json() or {}
        feats = js.get("features", []) or []
    except Exception:
        return []

    out = []
    for f in feats:
        props = f.get("properties", {}) or {}
        cc = (props.get("countrycode") or props.get("country", "")).upper()

        # filtro paese: se c'è e non è quello selezionato, saltiamo
        if cc and iso2 and cc != iso2.upper():
            continue

        name = props.get("name") or props.get("city") or props.get("state") or ""
        admin1 = props.get("state") or props.get("county") or ""
        label_core = ", ".join([p for p in [name, admin1] if p])

        geom = f.get("geometry", {}) or {}
        lon, lat = geom.get("coordinates", [None, None])
        if lat is None or lon is None:
            continue

        lab = f"{_flag(cc)}  {label_core}" if cc else label_core
        key = f"{lab}|||{lat:.6f},{lon:.6f}"
        out.append(
            (key, {"lat": float(lat), "lon": float(lon), "label": lab, "addr": props})
        )
    return out


def _search_function_factory(iso2: str):
    """
    Funzione che viene passata a st_searchbox.
    Usa Nominatim e, se non trova nulla, Photon.
    Popola st.session_state["_options"] con i payload.
    """
    def _search(q: str):
        q = (q or "").strip()
        st.session_state["_options"] = {}

        if len(q) < 2:
            return []

        results = _search_nominatim(q, iso2)
        if not results:
            results = _search_photon(q, iso2)

        keys = []
        for key, payload in results:
            st.session_state["_options"][key] = payload
            keys.append(key)
        return keys

    return _search


# -------------------- API principale: location_searchbox --------------------
def location_searchbox(T, iso2: str, key: str = "place"):
    """
    Widget di ricerca località.
    - Nominatim + Photon
    - Mantiene in sessione lat/lon/label.
    Ritorna sempre (lat, lon, label).
    """
    selected = st_searchbox(
        search_function=_search_function_factory(iso2),
        key=key,
        placeholder=T["search_ph"],
        debounce=400,
        clear_on_submit=False,
        default=None,
    )

    # valori di fallback/persistiti
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    # se l’utente ha scelto un suggerimento, aggiorniamo
    if selected and "|||" in selected and "_options" in st.session_state:
        info = (st.session_state["_options"] or {}).get(selected)
        if info:
            lat = float(info.get("lat", lat))
            lon = float(info.get("lon", lon))
            label = str(info.get("label", label))
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = label
            # reset di eventuali click sulla mappa
            st.session_state["_last_click"] = None

    return lat, lon, label
