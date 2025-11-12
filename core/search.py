# core/search.py
# Ricerca località: provider 1 = Open-Meteo Geocoding (rapido)
# fallback provider 2 = Nominatim (OSM) con pre-filtro paese
# Espone: place_search_ui(T, iso2, key_prefix="place") -> (lat, lon, label)

from __future__ import annotations
import time, unicodedata, requests
from typing import List, Dict, Any, Tuple
import streamlit as st
from streamlit_searchbox import st_searchbox

# ---------- Config ----------
UA = {
    # Nota: per Nominatim è consigliato includere un contatto (url o email)
    "User-Agent": "telemark-wax-pro/1.2 (+https://telemarkskihire.com)"
}
NOMINATIM_MIN_DELAY_S = 1.0  # rate-limit suggerito da OSM

# ---------- Utils ----------
def _flag(cc: str | None) -> str:
    """Converte ISO2 (es. 'IT') in bandiera emoji, fallback bianca in caso di errori."""
    try:
        if not cc:
            return "🏳️"
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

def _concise_label(addr_name: str, admin: str | None, cc: str | None) -> str:
    parts = [p for p in [addr_name, admin] if p]
    s = ", ".join(parts) if parts else (addr_name or "")
    return f"{s} — {cc.upper()}" if cc else s

def _norm(s: str) -> str:
    # per dedup: toglie accenti e normalizza
    return unicodedata.normalize("NFKD", s or "").encode("ASCII", "ignore").decode().lower().strip()

# ---------- PROVIDER 1: Open-Meteo Geocoding (veloce) ----------
@st.cache_data(ttl=3600, show_spinner=False)
def _om_geocode(name: str, iso2: str | None, lang: str = "it") -> List[Dict[str, Any]]:
    params = {
        "name": name,
        "count": 12,
        "language": (lang or "en").lower(),
        "format": "json",
    }
    if iso2:
        params["country"] = iso2.upper()

    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params=params, headers=UA, timeout=8
    )
    r.raise_for_status()
    j = r.json() or {}
    results: List[Dict[str, Any]] = []
    for it in (j.get("results") or []):
        city  = it.get("name") or ""
        admin = it.get("admin1") or it.get("admin2") or it.get("country")
        cc    = (it.get("country_code") or (iso2 or "")).upper()
        lat   = float(it.get("latitude"))
        lon   = float(it.get("longitude"))
        label_core = _concise_label(city, admin, cc)
        disp  = f"{_flag(cc)}  {label_core}"
        results.append({
            "label": disp,           # visibile (con bandiera)
            "lat": lat, "lon": lon, "cc": cc,
            "raw_label": label_core  # per dedup
        })
    return results

# ---------- PROVIDER 2: Nominatim (OSM) ----------
_last_nom_call_ts = 0.0

@st.cache_data(ttl=3600, show_spinner=False)
def _osm_geocode(name: str, iso2: str | None, lang: str = "it") -> List[Dict[str, Any]]:
    # Rispetta rate-limit (anche se cache riduce molto il rischio)
    global _last_nom_call_ts
    now = time.time()
    if now - _last_nom_call_ts < NOMINATIM_MIN_DELAY_S:
        time.sleep(NOMINATIM_MIN_DELAY_S - (now - _last_nom_call_ts))
    _last_nom_call_ts = time.time()

    params = {
        "q": name,
        "format": "json",
        "limit": 12,
        "addressdetails": 1,
        "accept-language": (lang or "en").lower(),
    }
    if iso2:
        params["countrycodes"] = iso2.lower()

    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params=params, headers=UA, timeout=10
    )
    r.raise_for_status()
    out: List[Dict[str, Any]] = []
    for it in (r.json() or []):
        addr  = it.get("address", {}) or {}
        name0 = (addr.get("village") or addr.get("town") or addr.get("city")
                 or addr.get("hamlet") or it.get("display_name", ""))
        admin = (addr.get("state") or addr.get("region") or addr.get("county"))
        cc    = ((addr.get("country_code") or (iso2 or "")).upper())
        lat   = float(it.get("lat", 0))
        lon   = float(it.get("lon", 0))
        label_core = _concise_label(name0, admin, cc)
        disp  = f"{_flag(cc)}  {label_core}"
        out.append({
            "label": disp, "lat": lat, "lon": lon, "cc": cc,
            "raw_label": label_core
        })
    return out

# ---------- merge + dedup ----------
def _merge_results(a: List[Dict[str, Any]] | None,
                   b: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for src in (a or []), (b or []):
        for it in src:
            key = (_norm(it.get("raw_label", "")),
                   round(float(it.get("lat", 0)), 4),
                   round(float(it.get("lon", 0)), 4))
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
    return out

# ---------- callback per st_searchbox ----------
def _search_callback_factory(iso2: str | None, lang_ui: str, key_prefix: str):
    def _cb(q: str) -> List[str]:
        if not q or len(q.strip()) < 2:
            return []
        # 1) OM (rapido) → 2) OSM (fallback)
        try:
            a = _om_geocode(q.strip(), iso2, lang_ui)
        except Exception:
            a = []
        try:
            b = _osm_geocode(q.strip(), iso2, lang_ui)
        except Exception:
            b = []
        merged = _merge_results(a, b)

        # salva mappa opzioni in sessione per risoluzione lat/lon
        ss_key = f"{key_prefix}__search_opts"
        st.session_state.setdefault(ss_key, {})
        out_strings: List[str] = []
        for it in merged:
            token = f"om|{it['lat']:.6f}|{it['lon']:.6f}|{it['cc']}"
            st.session_state[ss_key][token] = it
            # Manteniamo il token nascosto all’utente, ma necessario per risalire ai dati
            out_strings.append(f"{token}  {it['label']}")
        return out_strings
    return _cb

# ---------- UI wrapper richiamabile dal main ----------
def place_search_ui(T: Dict[str, str], iso2: str | None, key_prefix: str = "place") -> Tuple[float, float, str]:
    """
    Disegna la searchbox e restituisce (lat, lon, label).
    Aggiorna anche st.session_state[f'{key_prefix}_lat'/'_lon'/'_label'].
    """
    # placeholder in base alla lingua
    ph = T.get("search_ph", "Cerca località…")
    # lingua dal dizionario (heuristic: 'it' se contiene parole italiane)
    lang_ui = "it" if ("Cerca" in ph or "Nazione" in (T.get("country", ""))) else "en"

    selected = st_searchbox(
        _search_callback_factory(iso2, lang_ui, key_prefix),
        key=f"{key_prefix}_sb",
        placeholder=ph,
        clear_on_submit=False,
        default=None
    )

    # Chiavi di stato namespaziate
    LAT_K = f"{key_prefix}_lat"
    LON_K = f"{key_prefix}_lon"
    LAB_K = f"{key_prefix}_label"
    OPTS_K = f"{key_prefix}__search_opts"

    # valori correnti persistiti (default Champoluc)
    lat = float(st.session_state.get(LAT_K, 45.83100))
    lon = float(st.session_state.get(LON_K, 7.73000))
    label = st.session_state.get(LAB_K, "🇮🇹  Champoluc, Valle d’Aosta — IT")

    if selected:
        # `selected` è la riga visibile. Il token è sempre in testa: om|lat|lon|CC
        token = selected.split("  ", 1)[0].strip()
        info = (st.session_state.get(OPTS_K) or {}).get(token)
        if info:
            lat = float(info["lat"])
            lon = float(info["lon"])
            label = info["label"]
            st.session_state[LAT_K] = lat
            st.session_state[LON_K] = lon
            st.session_state[LAB_K] = label

    # badge riassunto (facoltativo, ma comodo)
    st.markdown(
        f"<div class='badge'>📍 {label} · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True
    )
    return lat, lon, label
