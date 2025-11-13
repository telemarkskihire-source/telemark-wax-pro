# core/search.py
# Ricerca località con Nominatim + Photon, robusta e con country prefilter

import time
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# ---- Costanti & helpers ----
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
    """Piccolo retry helper: se esauriti i tentativi, rilancia l'ultimo errore."""
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.5 ** i))


# --------------------------------------------------------------------
# UI widgets
# --------------------------------------------------------------------
def country_selectbox(T):
    """Selectbox paese → ritorna codice ISO2 (IT, FR, …)."""
    label = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
    return COUNTRIES[label]


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
    parts = [p for p in (name, admin1) if p]
    return ", ".join(parts)


# --------------------------------------------------------------------
# sorgenti ricerca
# --------------------------------------------------------------------
def _search_nominatim(q: str, iso2: str):
    """Ricerca principale (Nominatim). Non alza mai eccezioni → [] in caso di problemi."""
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        def go():
            return requests.get(
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

        r = _retry(go)
        r.raise_for_status()
        js = r.json() or []
    except Exception:
        # rate limit / errore → nessuna opzione ma niente blocchi rossi
        return []

    out = []
    for it in js:
        addr = it.get("address", {}) or {}
        lab_core = _concise_label(addr, it.get("display_name", ""))
        cc = (addr.get("country_code") or "").upper()
        lab = f"{_flag(cc)}  {lab_core}" if cc else lab_core
        try:
            lat = float(it.get("lat", 0.0))
            lon = float(it.get("lon", 0.0))
        except Exception:
            continue
        key = f"{lab}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": lat, "lon": lon, "label": lab, "addr": addr}))
    return out


def _search_photon(q: str, iso2: str):
    """Fallback Photon (Komoot). Anche qui: mai errori mostrati a schermo."""
    q = (q or "").strip()
    if len(q) < 2:
        return []

    try:
        r = requests.get(
            "https://photon.komoot.io/api",
            params={"q": q, "limit": 10, "lang": "it"},
            headers={"User-Agent": BASE_UA},
            timeout=8,
        )
        r.raise_for_status()
        feats = (r.json() or {}).get("features", []) or []
    except Exception:
        return []

    out = []
    for f in feats:
        props = f.get("properties", {}) or {}
        cc = (props.get("countrycode") or props.get("country", "")).upper()
        if cc and cc != iso2.upper():
            continue

        name = props.get("name") or props.get("city") or props.get("state") or ""
        admin1 = props.get("state") or props.get("county") or ""
        label_core = ", ".join([p for p in (name, admin1) if p])

        geom = f.get("geometry", {}) or {}
        lon, lat = (geom.get("coordinates") or [None, None])[:2]
        if lat is None or lon is None:
            continue

        lab = f"{_flag(cc)}  {label_core}" if cc else label_core
        key = f"{lab}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": float(lat), "lon": float(lon), "label": lab, "addr": {}}))
    return out


def _search_function_factory(iso2: str):
    """Factory per la funzione da passare a st_searchbox (chiude iso2)."""

    def _search(q: str):
        # reset mappa risultati
        st.session_state._options = {}
        try:
            res = _search_nominatim(q, iso2)
            if not res:
                res = _search_photon(q, iso2)
        except Exception:
            # estrema difesa: nessun errore in UI
            res = []

        keys = []
        for key, payload in res:
            st.session_state._options[key] = payload
            keys.append(key)
        return keys

    return _search


# --------------------------------------------------------------------
# Searchbox pubblico
# --------------------------------------------------------------------
def location_searchbox(T, iso2: str, key: str = "place"):
    """
    Widget di ricerca località.
    Ritorna sempre una terna (lat, lon, label), usando session_state come fallback.
    """

    selected = st_searchbox(
        search_function=_search_function_factory(iso2),
        key=key,
        placeholder=T["search_ph"],
        debounce=400,
        clear_on_submit=False,
        default=None,
    )

    # Defaults/persistiti
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    # Se l'utente sceglie un suggerimento, aggiorniamo
    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state._options.get(selected)
        if info:
            try:
                lat = float(info["lat"])
                lon = float(info["lon"])
                label = str(info["label"])
            except Exception:
                pass
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = label
            st.session_state["_last_click"] = None  # reset mappa

    return lat, lon, label
