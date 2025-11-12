# core/search.py
# API pubbliche per streamlit_app.py:
#   - COUNTRIES
#   - country_selectbox(T, key="country_sel") -> str ISO2
#   - location_searchbox(T, iso2, key="place") -> (lat: float, lon: float, label: str)
#
# NOTE:
# - location_searchbox restituisce SEMPRE una tupla (mai None), usando valori persistiti o default (Champoluc)
# - Popola anche st.session_state._options[token] = {lat, lon, label}
# - Usa streamlit_searchbox se presente, altrimenti fallback nativo (text_input + selectbox)

from __future__ import annotations
import time
from typing import Dict, List, Tuple, Optional
import requests
import streamlit as st

# ---------- Config ----------
BASE_UA = "telemark-wax-pro/1.2 (+https://telemarkskihire.com)"
HEADERS = {"User-Agent": BASE_UA, "Accept": "application/json"}
EMAIL = st.secrets.get("NOMINATIM_EMAIL")
if EMAIL:
    HEADERS["From"] = EMAIL
HTTP_TIMEOUT = 8
NOMINATIM_MIN_DELAY_S = 1.0

# ---------- Paesi (pubblici) ----------
COUNTRIES: Dict[str, str] = {
    "Italia": "IT", "Svizzera": "CH", "Francia": "FR", "Austria": "AT",
    "Germania": "DE", "Spagna": "ES", "Norvegia": "NO", "Svezia": "SE"
}

# ---------- Utils ----------
def _flag(cc: Optional[str]) -> str:
    try:
        if not cc: return "🏳️"
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

def _label_from_addr(addr: dict, fallback: str) -> str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin = addr.get("state") or addr.get("region") or addr.get("county") or ""
    parts = [p for p in [name, admin] if p]
    core = ", ".join([p for p in parts if p]) or fallback
    cc = (addr.get("country_code") or "").upper()
    return f"{_flag(cc)}  {core}" if core else fallback

def _retry(fn, tries=2, base_sleep=0.8):
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(base_sleep * (1.5 ** i))

# ---------- Provider ricerca ----------
def _search_nominatim(q: str, iso2: str) -> List[Tuple[str, dict]]:
    if not q or len(q.strip()) < 2:
        return []
    # rate limit minimo
    now = time.time()
    last = st.session_state.get("__nom_last_ts", 0.0)
    if now - last < NOMINATIM_MIN_DELAY_S:
        time.sleep(NOMINATIM_MIN_DELAY_S - (now - last))
    st.session_state["__nom_last_ts"] = time.time()

    try:
        def go():
            return requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": 10, "addressdetails": 1,
                        "countrycodes": iso2.lower()},
                headers=HEADERS, timeout=HTTP_TIMEOUT
            )
        r = _retry(go); r.raise_for_status()
        js = r.json() or []
        out = []
        for it in js:
            addr = it.get("address", {}) or {}
            lab = _label_from_addr(addr, it.get("display_name", ""))
            lat = float(it.get("lat", 0)); lon = float(it.get("lon", 0))
            key = f"{lab}|||{lat:.6f},{lon:.6f}"
            out.append((key, {"lat": lat, "lon": lon, "label": lab, "addr": addr}))
        return out
    except Exception:
        return []

def _search_photon(q: str, iso2: str) -> List[Tuple[str, dict]]:
    # Fallback (Komoot Photon) con filtro client-side su countrycode
    if not q or len(q.strip()) < 2:
        return []
    try:
        r = requests.get(
            "https://photon.komoot.io/api",
            params={"q": q, "limit": 10, "lang": "it"},
            headers={"User-Agent": BASE_UA}, timeout=HTTP_TIMEOUT
        )
        r.raise_for_status()
        js = r.json() or {}
        feats = js.get("features", []) or []
        out = []
        for f in feats:
            props = f.get("properties", {}) or {}
            cc = (props.get("countrycode") or props.get("country", "")).upper()
            if cc and cc != iso2.upper():
                continue
            name = props.get("name") or props.get("city") or props.get("state") or ""
            admin = props.get("state") or props.get("county") or ""
            core = ", ".join([p for p in [name, admin] if p]) or name or ""
            lab = f"{_flag(cc)}  {core}" if core else (name or "—")
            lon, lat = f.get("geometry", {}).get("coordinates", [None, None])
            if lat is None or lon is None:
                continue
            key = f"{lab}|||{float(lat):.6f},{float(lon):.6f}"
            out.append((key, {"lat": float(lat), "lon": float(lon), "label": lab, "addr": {}}))
        return out
    except Exception:
        return []

def _search_places(q: str, iso2: str) -> List[str]:
    """Ritorna lista di chiavi stringa e popola st.session_state._options."""
    st.session_state._options = {}
    results = _search_nominatim(q, iso2)
    if not results:
        results = _search_photon(q, iso2)
    keys: List[str] = []
    for key, payload in results:
        st.session_state._options[key] = payload
        keys.append(key)
    return keys

# ---------- Shim per st_searchbox ----------
try:
    from streamlit_searchbox import st_searchbox as _ext_st_searchbox
except Exception:
    _ext_st_searchbox = None

def _shim_searchbox(search_function, key, placeholder="", clear_on_submit=False, debounce=300, default=None):
    """Se il componente esterno esiste lo usa, altrimenti fallback nativo."""
    if _ext_st_searchbox is not None:
        try:
            return _ext_st_searchbox(
                search_function=search_function,
                key=key,
                placeholder=placeholder,
                clear_on_submit=clear_on_submit,
                debounce=debounce,
                default=default,
            )
        except Exception:
            pass  # fallback sotto

    # Fallback nativo (text_input + selectbox)
    q_key = f"{key}__q"; sel_key = f"{key}__sel"
    q = st.text_input(placeholder or "Search…", key=q_key, value="")
    options: List[str] = []
    if q and len(q.strip()) >= 2:
        try:
            options = search_function(q) or []
        except Exception:
            options = []
    if options:
        prev = st.session_state.get(sel_key)
        idx = options.index(prev) if prev in options else 0
        return st.selectbox("Risultati", options=options, index=idx, key=sel_key)
    return None

# ---------- API pubbliche richieste dal main ----------
def country_selectbox(T: Dict[str, str], key: str = "country_sel") -> str:
    """Disegna select paese e restituisce ISO2."""
    labels = list(COUNTRIES.keys())
    default_idx = 0
    cur = st.session_state.get(key)
    if cur in labels:
        default_idx = labels.index(cur)
    sel = st.selectbox(T.get("country", "Country"), labels, index=default_idx, key=key)
    return COUNTRIES[sel]

def location_searchbox(T: Dict[str, str], iso2: str, key: str = "place") -> Tuple[float, float, str]:
    """
    Mostra la casella di ricerca e restituisce SEMPRE (lat, lon, label).
    - Se l'utente seleziona un risultato, salva in session_state e ritorna quello.
    - Se non ha selezionato ancora nulla, ritorna i valori persistiti oppure i default (Champoluc).
    """
    ph = T.get("search_ph", "Cerca…")

    selected = _shim_searchbox(
        search_function=lambda q: _search_places(q, iso2),
        key=key,
        placeholder=ph,
        clear_on_submit=False,
        debounce=400,
        default=None
    )

    # default/persistiti
    lat = float(st.session_state.get("lat", 45.83100))
    lon = float(st.session_state.get("lon", 7.73000))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state._options.get(selected)
        if info:
            lat, lon, label = float(info["lat"]), float(info["lon"]), str(info["label"])
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = label

    return lat, lon, label

# --- COMPAT SHIM: garantisce che location_searchbox ritorni SEMPRE (lat, lon, label) ---
def __loc_tuple_wrapper(T, iso2, key: str = "place"):
    try:
        res = _location_searchbox_impl(T, iso2, key)  # se esiste l'impl reale
    except NameError:
        # se non c'è un'impl separata, prova a chiamare l'attuale location_searchbox
        try:
            res = location_searchbox(T, iso2, key)  # type: ignore
        except Exception:
            res = None

    if isinstance(res, tuple) and len(res) == 3:
        return res

    # gestisci key/None -> fallback ai persistiti/default
    if isinstance(res, str) and "|||" in res and "_options" in st.session_state:
        info = (st.session_state._options or {}).get(res, {})
        lat = float(info.get("lat", st.session_state.get("lat", 45.831)))
        lon = float(info.get("lon", st.session_state.get("lon", 7.730)))
        lab = info.get("label", st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT"))
        return lat, lon, lab

    # fallback duro
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    lab = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")
    return lat, lon, lab

# conserva l'impl attuale (se c'è) e poi SOSTITUISCI l'export con wrapper
try:
    _location_searchbox_impl = location_searchbox  # salva l’originale
except NameError:
    pass
location_searchbox = __loc_tuple_wrapper  # <-- da qui in poi ritorna sempre una tupla
