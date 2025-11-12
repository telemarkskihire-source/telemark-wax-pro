# core/search.py
# Ricerca località con prefiltro paese.
# Espone:
#   - COUNTRIES
#   - country_selectbox(T, key="country_sel") -> str (iso2)
#   - location_searchbox(T, iso2, key="place") -> str | None  (chiave selezionata)
#     (popola anche st.session_state._options[token] = {lat, lon, label})
# Opzionale:
#   - place_search_ui(T, iso2, key_prefix="place") -> (lat, lon, label)

from __future__ import annotations
import time, os, requests, unicodedata
from typing import Dict, Any, List, Tuple, Optional
import streamlit as st

# ---------------- Config / Headers ----------------
BASE_UA = "telemark-wax-pro/1.2 (+https://telemarkskihire.com)"
HEADERS = {"User-Agent": BASE_UA, "Accept": "application/json"}
NOMINATIM_EMAIL = st.secrets.get("NOMINATIM_EMAIL")
if NOMINATIM_EMAIL:
    HEADERS["From"] = NOMINATIM_EMAIL  # consigliato da Nominatim
HTTP_TIMEOUT = 8
NOMINATIM_MIN_DELAY_S = 1.0

# ---------------- Paesi esposti (compatibile con streamlit_app.py) ----------------
COUNTRIES: Dict[str,str] = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}

# ---------------- Utils ----------------
def _flag(cc: Optional[str]) -> str:
    try:
        if not cc: return "🏳️"
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

def _concise_label_from_addr(addr:dict, fallback:str)->str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    parts = [p for p in [name, admin1] if p]
    return ", ".join([p for p in parts if p])

def _retry(func, attempts=2, sleep=0.8):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts-1: raise
            time.sleep(sleep*(1.5**i))

# ---------------- Search providers ----------------
def _search_nominatim(q:str, iso2:str) -> List[Tuple[str,dict]]:
    if not q or len(q.strip()) < 2:
        return []
    # rate-limit minimo
    now = time.time()
    last = st.session_state.get("__nom_last_ts", 0.0)
    if now - last < NOMINATIM_MIN_DELAY_S:
        time.sleep(NOMINATIM_MIN_DELAY_S - (now - last))
    st.session_state["__nom_last_ts"] = time.time()

    try:
        def go():
            return requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q, "format": "json", "limit": 10, "addressdetails": 1,
                    "countrycodes": iso2.lower()
                },
                headers=HEADERS, timeout=HTTP_TIMEOUT
            )
        r = _retry(go); r.raise_for_status()
        js = r.json() or []
        out = []
        for it in js:
            addr = it.get("address",{}) or {}
            lab_core = _concise_label_from_addr(addr, it.get("display_name",""))
            cc = (addr.get("country_code") or "").upper()
            lab = f"{_flag(cc)}  {lab_core}" if cc else lab_core
            lat = float(it.get("lat",0)); lon=float(it.get("lon",0))
            key = f"{lab}|||{lat:.6f},{lon:.6f}"
            out.append((key, {"lat":lat,"lon":lon,"label":lab,"addr":addr}))
        return out
    except Exception:
        return []

def _search_photon(q:str, iso2:str) -> List[Tuple[str,dict]]:
    # Fallback (Komoot Photon) – filtriamo client-side su countrycode
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
        feats = js.get("features",[]) or []
        out=[]
        for f in feats:
            props = f.get("properties",{}) or {}
            cc = (props.get("countrycode") or props.get("country","")).upper()
            if cc and cc != iso2.upper():
                continue
            name = props.get("name") or props.get("city") or props.get("state") or ""
            admin1 = props.get("state") or props.get("county") or ""
            label_core = ", ".join([p for p in [name, admin1] if p])
            lab = f"{_flag(cc)}  {label_core}" if cc else label_core
            lon, lat = f.get("geometry",{}).get("coordinates",[None,None])
            if lat is None or lon is None: continue
            key = f"{lab}|||{float(lat):.6f},{float(lon):.6f}"
            out.append((key, {"lat":float(lat),"lon":float(lon),"label":lab,"addr":{}}))
        return out
    except Exception:
        return []

def _search_places(q:str, iso2:str) -> List[str]:
    """Ritorna lista di chiavi stringa e popola st.session_state._options."""
    st.session_state._options = {}
    results = _search_nominatim(q, iso2)
    if not results:
        results = _search_photon(q, iso2)
    keys=[]
    for key, payload in results:
        st.session_state._options[key] = payload
        keys.append(key)
    return keys

# ---------------- Shim per st_searchbox ----------------
try:
    from streamlit_searchbox import st_searchbox as _ext_st_searchbox
except Exception:
    _ext_st_searchbox = None

def _shim_searchbox(search_function, key, placeholder="", clear_on_submit=False, debounce=300, default=None):
    """
    Compatibile con streamlit_searchbox. Se disponibile usa il componente,
    altrimenti fallback nativo (text_input + selectbox).
    """
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
            pass  # se esplode, usa fallback

    # Fallback nativo
    q_key = f"{key}__q"
    sel_key = f"{key}__sel"
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
        selected = st.selectbox("Risultati", options=options, index=idx, key=sel_key)
    else:
        selected = None
    return selected

# ---------------- API attese dallo streamlit_app.py ----------------
def country_selectbox(T: Dict[str,str], key: str = "country_sel") -> str:
    """
    Disegna la select del Paese e restituisce l'ISO2 selezionato.
    """
    labels = list(COUNTRIES.keys())
    default_idx = 0
    current = st.session_state.get(key)
    if current in labels:
        default_idx = labels.index(current)
    sel_country = st.selectbox(T.get("country","Country"), labels, index=default_idx, key=key)
    return COUNTRIES[sel_country]

def location_searchbox(T: Dict[str,str], iso2: str, key: str = "place") -> Optional[str]:
    """
    Mostra la casella di ricerca luogo e restituisce la *chiave selezionata* (stringa),
    es. '🇮🇹  Champoluc, Valle d’Aosta — IT|||45.831000,7.730000'.
    Inoltre popola st.session_state._options[key] = {lat, lon, label}.
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
    return selected

# ---------------- Opzionale: API a ritorno diretto (lat, lon, label) ----------------
def place_search_ui(T: Dict[str,str], iso2: str, key_prefix: str = "place") -> Tuple[float, float, str]:
    """
    Variante comoda: disegna la searchbox e gestisce direttamente lo stato.
    Ritorna (lat, lon, label) e aggiorna st.session_state['lat'/'lon'/'place_label'].
    """
    selected = location_searchbox(T, iso2, key=key_prefix)

    # default: Champoluc
    lat = float(st.session_state.get("lat", 45.83100))
    lon = float(st.session_state.get("lon", 7.73000))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state._options.get(selected)
        if info:
            lat, lon, label = info["lat"], info["lon"], info["label"]
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = label

    st.markdown(
        f"<div class='badge'>📍 <b>{label}</b> · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True
    )
    return lat, lon, label
