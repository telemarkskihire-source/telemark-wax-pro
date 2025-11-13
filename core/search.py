# core/search.py
# Ricerca località per Telemark · Pro Wax & Tune
# - Usa Nominatim (OSM) + fallback Photon
# - Filtra preferibilmente località sciistiche
# - Gestisce qualsiasi errore di rete senza far crashare l'app

import time
from typing import Dict, Any, List, Tuple, Optional

import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# ----------------- Costanti & helpers di base -----------------

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
    """Trasforma IT -> 🇮🇹, ecc. Se qualcosa va storto, restituisce una bandiera neutra."""
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"


BASE_UA = "telemark-wax-pro/1.0 (+https://telemarkskihire.com)"
NOMINATIM_EMAIL = st.secrets.get("NOMINATIM_EMAIL", None)

HEADERS_NOM: Dict[str, str] = {
    "User-Agent": BASE_UA,
    "Accept": "application/json",
    "Accept-Language": "it,en;q=0.8",
    "Referer": "https://telemarkskihire.com",
}
if NOMINATIM_EMAIL:
    HEADERS_NOM["From"] = NOMINATIM_EMAIL

SKI_KEYWORDS = [
    "ski",
    "skigebiet",
    "skistation",
    "station de ski",
    "sciistica",
    "impianti di risalita",
    "piste da sci",
    "piste sci",
    "piste-ski",
    "telecabina",
    "teleferico",
    "télécabine",
    "funivia",
    "seggiovia",
    "chairlift",
    "aerialway",
]


def _is_skiish(text: str) -> bool:
    """Heuristica semplice per capire se una descrizione 'sa di' località sciistica."""
    t = text.lower()
    return any(kw in t for kw in SKI_KEYWORDS)


def _retry_request(
    method: str,
    url: str,
    *,
    attempts: int = 2,
    sleep: float = 0.8,
    **kwargs: Any,
) -> Optional[requests.Response]:
    """
    Richiesta HTTP con retry morbido.
    In caso di fallimento definitivo restituisce None (mai solleva eccezioni verso l'alto).
    """
    for i in range(attempts):
        try:
            resp = requests.request(method, url, timeout=kwargs.pop("timeout", 8), **kwargs)
            return resp
        except requests.exceptions.RequestException:
            if i == attempts - 1:
                return None
            time.sleep(sleep * (1.5 ** i))
    return None


def _concise_label(addr: Dict[str, Any], fallback: str) -> str:
    """
    Crea una descrizione breve tipo 'Champoluc, Valle d'Aosta'.
    Niente lat/lon nel testo, solo nome + regione.
    """
    name = (
        addr.get("village")
        or addr.get("hamlet")
        or addr.get("town")
        or addr.get("city")
        or addr.get("residential")
        or addr.get("locality")
        or fallback
    )
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    parts = [p for p in [name, admin1] if p]
    return ", ".join(parts)


# ----------------- SEARCH: Nominatim & Photon -----------------

def _search_nominatim(q: str, iso2: Optional[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Cerca usando Nominatim.
    - Primo tentativo: '<q> ski' per privilegiare resort.
    - Se niente, fallback: '<q>' normale.
    - Filtra preferibilmente risultati 'skiish'.
    Ritorna lista di (key, payload).
    """
    if not q or len(q.strip()) < 2:
        return []

    q = q.strip()

    def _do_query(query_text: str) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "q": query_text,
            "format": "json",
            "limit": 10,
            "addressdetails": 1,
        }
        if iso2:
            params["countrycodes"] = iso2.lower()

        resp = _retry_request(
            "GET",
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=HEADERS_NOM,
            timeout=8,
        )
        if resp is None:
            return []
        try:
            js = resp.json()
        except ValueError:
            return []
        return js or []

    raw = _do_query(f"{q} ski")
    if not raw:
        raw = _do_query(q)

    if not raw:
        return []

    collected: List[Dict[str, Any]] = []
    for it in raw:
        addr = it.get("address", {}) or {}
        disp = it.get("display_name", "") or ""
        cc = (addr.get("country_code") or "").upper()

        full_text = f"{disp} {addr}"
        is_ski = _is_skiish(full_text)

        lab_core = _concise_label(addr, disp)
        label = f"{_flag(cc)}  {lab_core}" if cc else lab_core

        try:
            lat = float(it.get("lat", 0) or 0)
            lon = float(it.get("lon", 0) or 0)
        except Exception:
            continue

        key = f"{label}|||{lat:.6f},{lon:.6f}"
        payload = {
            "lat": lat,
            "lon": lon,
            "label": label,
            "addr": addr,
        }
        collected.append({"key": key, "payload": payload, "is_ski": is_ski})

    ski_only = [c for c in collected if c["is_ski"]]
    chosen = ski_only if ski_only else collected

    out: List[Tuple[str, Dict[str, Any]]] = []
    for c in chosen:
        out.append((c["key"], c["payload"]))
    return out


def _search_photon(q: str, iso2: Optional[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Fallback su Photon (Komoot).
    Non forza 'ski' nel testo, ma applica comunque filtro skiish se possibile.
    """
    if not q or len(q.strip()) < 2:
        return []

    q = q.strip()

    resp = _retry_request(
        "GET",
        "https://photon.komoot.io/api",
        params={"q": q, "limit": 10, "lang": "it"},
        headers={"User-Agent": BASE_UA},
        timeout=8,
    )
    if resp is None:
        return []

    try:
        feats = (resp.json() or {}).get("features", []) or []
    except ValueError:
        return []

    collected: List[Dict[str, Any]] = []
    for f in feats:
        props = f.get("properties", {}) or {}
        cc = (props.get("countrycode") or props.get("country", "") or "").upper()
        if iso2 and cc and cc != iso2.upper():
            continue

        name = props.get("name") or props.get("city") or props.get("state") or ""
        admin1 = props.get("state") or props.get("county") or ""
        label_core = ", ".join([p for p in [name, admin1] if p])

        geom = f.get("geometry", {}) or {}
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]

        try:
            lat = float(lat)
            lon = float(lon)
        except Exception:
            continue

        disp = props.get("name", "") or ""
        full_text = f"{disp} {label_core} {props}"
        is_ski = _is_skiish(full_text)

        label = f"{_flag(cc)}  {label_core}" if cc else label_core
        key = f"{label}|||{lat:.6f},{lon:.6f}"
        payload = {
            "lat": lat,
            "lon": lon,
            "label": label,
            "addr": props,
        }
        collected.append({"key": key, "payload": payload, "is_ski": is_ski})

    ski_only = [c for c in collected if c["is_ski"]]
    chosen = ski_only if ski_only else collected

    out: List[Tuple[str, Dict[str, Any]]] = []
    for c in chosen:
        out.append((c["key"], c["payload"]))
    return out


def _search_function_factory(iso2: Optional[str]):
    """
    Factory per la funzione da dare a st_searchbox.
    Si occupa di:
      - svuotare e riempire st.session_state._options
      - unire risultati Nominatim + fallback Photon
    """
    def _search(q: str) -> List[str]:
        st.session_state._options = {}

        res_nom = _search_nominatim(q, iso2)
        res_pho: List[Tuple[str, Dict[str, Any]]] = []

        if not res_nom:
            res_pho = _search_photon(q, iso2)
            results = res_pho
        else:
            results = res_nom

        keys: List[str] = []
        for key, payload in results:
            st.session_state._options[key] = payload
            keys.append(key)
        return keys

    return _search


# ----------------- UI helpers esposti allo streamlit_app -----------------

def country_selectbox(T: Dict[str, str]) -> str:
    """
    Se vuoi ripristinare il filtro per nazione:
      iso2 = country_selectbox(T)
    Per ora non è obbligatorio usarlo nel tuo streamlit_app.py.
    """
    label = T.get("country", "Nazione")
    country_name = st.selectbox(label, list(COUNTRIES.keys()), index=0, key="country_sel")
    return COUNTRIES[country_name]


def location_searchbox(T: Dict[str, str], iso2: Optional[str] = None, key: str = "place"):
    """
    Searchbox principale.
    - Usa _search_function_factory(iso2) per i suggerimenti.
    - Restituisce SEMPRE una tripla (lat, lon, label), usando valori
      di default / persistiti in session_state se la ricerca fallisce.
    """
    # searchbox
    selected = st_searchbox(
        search_function=_search_function_factory(iso2),
        key=key,
        placeholder=T.get("search_ph", "Cerca località…"),
        debounce=400,
        clear_on_submit=False,
        default=None,
    )

    # defaults / valori persistiti
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    # se l'utente ha scelto un suggerimento valido, aggiorna
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
            # reset eventuali selezioni mappa
            st.session_state["_last_click"] = None

    return lat, lon, label
