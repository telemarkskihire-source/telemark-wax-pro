# core/search.py
# Ricerca località "intelligente" per Telemark · Pro Wax & Tune
# - Suggerimenti solo per potenziali resort sciistici (via Overpass)
# - Compatibile con streamlit_searchbox

from __future__ import annotations

import time
from typing import Dict, List, Tuple, Any

import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# ---------------- Costanti & helpers base ----------------

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

# Overpass per capire se c'è un comprensorio sci
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_HEADERS = {
    "User-Agent": BASE_UA,
    "Accept": "application/json",
}

def _retry(func, attempts: int = 2, sleep: float = 0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.5 ** i))

# ---------------- Widgets UI di base ----------------

def country_selectbox(T: Dict[str, str]) -> str:
    """
    Selectbox paese. Ritorna codice ISO2 (es. 'IT').
    """
    label = T["country"]
    default_key = st.session_state.get("country_sel", list(COUNTRIES.keys())[0])
    sel = st.selectbox(label, list(COUNTRIES.keys()), index=list(COUNTRIES.keys()).index(default_key), key="country_sel")
    return COUNTRIES[sel]

def _concise_label(addr: Dict[str, Any], fallback: str) -> str:
    """
    Crea una label leggibile tipo 'Champoluc, Valle d’Aosta — IT'.
    """
    name = (
        addr.get("neighbourhood")
        or addr.get("hamlet")
        or addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or addr.get("locality")
        or fallback
    )
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    core = ", ".join(parts) if parts else fallback
    return f"{core} — {cc}" if cc else core

# ---------------- Nominatim & Photon ----------------

def _search_nominatim(q: str, iso2: str | None) -> List[Tuple[str, Dict[str, Any]]]:
    if not q or len(q.strip()) < 2:
        return []

    def go():
        params = {
            "q": q,
            "format": "json",
            "limit": 10,
            "addressdetails": 1,
        }
        if iso2:
            params["countrycodes"] = iso2.lower()
        # restringiamo un po' il tipo di oggetto
        params["extratags"] = 1
        return requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=HEADERS_NOM,
            timeout=8,
        )

    r = _retry(go)
    r.raise_for_status()
    js = r.json() or []

    out: List[Tuple[str, Dict[str, Any]]] = []
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

def _search_photon(q: str, iso2: str | None) -> List[Tuple[str, Dict[str, Any]]]:
    if not q or len(q.strip()) < 2:
        return []

    r = requests.get(
        "https://photon.komoot.io/api",
        params={"q": q, "limit": 10, "lang": "it"},
        headers={"User-Agent": BASE_UA},
        timeout=8,
    )
    r.raise_for_status()
    feats = (r.json() or {}).get("features", []) or []

    out: List[Tuple[str, Dict[str, Any]]] = []
    for f in feats:
        props = f.get("properties", {}) or {}
        cc = (props.get("countrycode") or props.get("country", "")).upper()
        if iso2 and cc and cc != iso2.upper():
            continue
        name = props.get("name") or props.get("city") or props.get("state") or ""
        admin1 = props.get("state") or props.get("county") or ""
        label_core = ", ".join([p for p in [name, admin1] if p])
        lon, lat = f.get("geometry", {}).get("coordinates", [None, None])
        if lat is None or lon is None:
            continue
        lab = f"{_flag(cc)}  {label_core}" if cc else label_core
        key = f"{lab}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat": float(lat), "lon": float(lon), "label": lab, "addr": {}}))
    return out

# ---------------- Filtro "solo resort sciistici" ----------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _has_ski_area(lat: float, lon: float, radius_km: int = 15) -> bool:
    """
    Ritorna True se in un raggio di ~radius_km ci sono piste / impianti (OSM/Overpass).
    È volutamente leggero: basta che esista QUALCOSA.
    """
    radius_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:20];
    (
      way(around:{radius_m},{lat},{lon})["piste:type"];
      relation(around:{radius_m},{lat},{lon})["piste:type"];
      way(around:{radius_m},{lat},{lon})["piste:difficulty"];
      relation(around:{radius_m},{lat},{lon})["route"="piste"];
      way(around:{radius_m},{lat},{lon})["aerialway"];
      node(around:{radius_m},{lat},{lon})["aerialway"];
    );
    out center 1;
    """

    try:
        r = requests.post(
            OVERPASS_URL,
            data=query.encode("utf-8"),
            headers=OVERPASS_HEADERS,
            timeout=25,
        )
        r.raise_for_status()
        elements = (r.json() or {}).get("elements", []) or []
        return len(elements) > 0
    except Exception:
        # se Overpass fallisce preferiamo "False": il filtro si occuperà di fare fallback
        return False

def _search_function_factory(iso2: str | None):
    """
    Factory per la funzione da dare a st_searchbox.
    Applica il filtro "solo resort sciistici" usando _has_ski_area.
    """
    def _search(q: str) -> List[str]:
        q = (q or "").strip()
        if len(q) < 2:
            return []

        # 1) Nominatim, 2) fallback Photon
        raw = _search_nominatim(q, iso2)
        if not raw:
            raw = _search_photon(q, iso2)

        # Nessun risultato, niente suggerimenti
        if not raw:
            st.session_state._options = {}
            return []

        # 2) filtro "ski area"
        filtered: List[Tuple[str, Dict[str, Any]]] = []
        for key, payload in raw:
            lat = float(payload.get("lat", 0.0))
            lon = float(payload.get("lon", 0.0))
            if _has_ski_area(lat, lon):
                filtered.append((key, payload))

        # se il filtro butta via tutto (Overpass giù, zona non mappata bene, ecc.)
        # usiamo la lista integra per non lasciare la search vuota
        final_list = filtered if filtered else raw

        # popola mappa opzioni → usata dopo da streamlit_app
        st.session_state._options = {}
        keys: List[str] = []
        for key, payload in final_list:
            st.session_state._options[key] = payload
            keys.append(key)
        return keys

    return _search

# ---------------- Entry principale per la app ----------------

def location_searchbox(T: Dict[str, str], iso2: str | None = None, key: str = "place"):
    """
    Widget di ricerca località.
    Ritorna SEMPRE (lat, lon, label).
    """
    selected = st_searchbox(
        search_function=_search_function_factory(iso2),
        key=key,
        placeholder=T["search_ph"],
        debounce=400,
        clear_on_submit=False,
        default=None,
    )

    # valori persistiti / default
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    # se l'utente ha scelto un suggerimento
    if selected and "|||" in selected and "_options" in st.session_state:
        info = (st.session_state._options or {}).get(selected)
        if info:
            try:
                lat = float(info["lat"])
                lon = float(info["lon"])
                label = str(info["label"])
                st.session_state["lat"] = lat
                st.session_state["lon"] = lon
                st.session_state["place_label"] = label
                # reset selezioni mappa eventualmente collegate
                st.session_state["_last_click"] = None
            except Exception:
                pass

    return lat, lon, label
