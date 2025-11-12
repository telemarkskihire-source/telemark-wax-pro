# core/search.py
# Ricerca località (solo Streamlit native: text_input + selectbox)
# Provider 1: Open-Meteo Geocoding (veloce)
# Provider 2: Nominatim (OSM) con pre-filtro paese
# API: place_search_ui(T, iso2, key_prefix="place") -> (lat, lon, label)

from __future__ import annotations
import time, unicodedata, requests
from typing import List, Dict, Any, Tuple, Optional
import streamlit as st

# ---------- Config ----------
UA = {"User-Agent": "telemark-wax-pro/1.2 (+https://telemarkskihire.com)"}
NOMINATIM_MIN_DELAY_S = 1.0  # rate-limit suggerito da OSM
HTTP_TIMEOUT = 8

# ---------- Cache minimale (compatibile con qualsiasi Streamlit) ----------
def _ss():
    st.session_state.setdefault("__search_cache", {})
    st.session_state.setdefault("__nom_last_ts", 0.0)
    return st.session_state["__search_cache"]

def _cache_get(key: str) -> Optional[Any]:
    item = _ss().get(key)
    if not item: return None
    val, exp = item
    if exp and time.time() > exp:
        del _ss()[key]
        return None
    return val

def _cache_put(key: str, val: Any, ttl_s: int = 3600):
    _ss()[key] = (val, time.time() + ttl_s if ttl_s else None)

# ---------- Utils ----------
def _flag(cc: Optional[str]) -> str:
    try:
        if not cc: return "🏳️"
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

def _concise_label(addr_name: str, admin: Optional[str], cc: Optional[str]) -> str:
    parts = [p for p in [addr_name, admin] if p]
    s = ", ".join(parts) if parts else (addr_name or "")
    return f"{s} — {cc.upper()}" if cc else s

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ASCII", "ignore").decode().lower().strip()

# ---------- HTTP helper ----------
def _http_get_json(url: str, params: dict, ttl_s: int) -> Any:
    key = f"GET|{url}|{sorted(params.items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    r = requests.get(url, params=params, headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    j = r.json()
    _cache_put(key, j, ttl_s=ttl_s)
    return j

# ---------- PROVIDER 1: Open-Meteo ----------
def _om_geocode(name: str, iso2: Optional[str], lang: str = "it") -> List[Dict[str, Any]]:
    params = {
        "name": name,
        "count": 12,
        "language": (lang or "en").lower(),
        "format": "json",
    }
    if iso2:
        params["country"] = iso2.upper()

    j = _http_get_json("https://geocoding-api.open-meteo.com/v1/search", params, ttl_s=3600) or {}
    results: List[Dict[str, Any]] = []
    for it in (j.get("results") or []):
        city  = it.get("name") or ""
        admin = it.get("admin1") or it.get("admin2") or it.get("country")
        cc    = (it.get("country_code") or (iso2 or "")).upper()
        lat   = float(it.get("latitude"))
        lon   = float(it.get("longitude"))
        label_core = _concise_label(city, admin, cc)
        disp  = f"{_flag(cc)}  {label_core}"
        results.append({"label": disp, "lat": lat, "lon": lon, "cc": cc, "raw_label": label_core})
    return results

# ---------- PROVIDER 2: Nominatim ----------
def _osm_geocode(name: str, iso2: Optional[str], lang: str = "it") -> List[Dict[str, Any]]:
    # rate-limit minimo
    now = time.time()
    last = st.session_state.get("__nom_last_ts", 0.0)
    if now - last < NOMINATIM_MIN_DELAY_S:
        time.sleep(NOMINATIM_MIN_DELAY_S - (now - last))
    st.session_state["__nom_last_ts"] = time.time()

    params = {
        "q": name,
        "format": "json",
        "limit": 12,
        "addressdetails": 1,
        "accept-language": (lang or "en").lower(),
    }
    if iso2:
        params["countrycodes"] = iso2.lower()

    j = _http_get_json("https://nominatim.openstreetmap.org/search", params, ttl_s=3600) or []
    out: List[Dict[str, Any]] = []
    for it in (j or []):
        addr  = it.get("address", {}) or {}
        name0 = (addr.get("village") or addr.get("town") or addr.get("city")
                 or addr.get("hamlet") or it.get("display_name", ""))
        admin = (addr.get("state") or addr.get("region") or addr.get("county"))
        cc    = ((addr.get("country_code") or (iso2 or "")).upper())
        lat   = float(it.get("lat", 0))
        lon   = float(it.get("lon", 0))
        label_core = _concise_label(name0, admin, cc)
        disp  = f"{_flag(cc)}  {label_core}"
        out.append({"label": disp, "lat": lat, "lon": lon, "cc": cc, "raw_label": label_core})
    return out

# ---------- merge + dedup ----------
def _merge_results(a: List[Dict[str, Any]] | None, b: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for src in (a or []), (b or []):
        for it in src:
            key = (_norm(it.get("raw_label", "")), round(float(it.get("lat", 0)), 4), round(float(it.get("lon", 0)), 4))
            if key in seen: continue
            seen.add(key)
            out.append(it)
    return out

# ---------- UI wrapper (solo componenti Streamlit) ----------
def place_search_ui(T: Dict[str, str], iso2: Optional[str], key_prefix: str = "place") -> Tuple[float, float, str]:
    """
    Disegna una searchbox nativa (text_input + selectbox) e restituisce (lat, lon, label).
    Aggiorna: st.session_state[f'{key_prefix}_lat'/'_lon'/'_label'].
    """
    # lingua / placeholder
    ph = T.get("search_ph", "Cerca località…")
    lang_ui = "it" if ("Cerca" in ph or "Nazione" in (T.get("country", ""))) else "en"

    # chiavi di stato
    LAT_K  = f"{key_prefix}_lat"
    LON_K  = f"{key_prefix}_lon"
    LAB_K  = f"{key_prefix}_label"
    OPTS_K = f"{key_prefix}__search_opts"
    Q_K    = f"{key_prefix}__query"
    SEL_K  = f"{key_prefix}__selected"

    # default Champoluc
    lat = float(st.session_state.get(LAT_K, 45.83100))
    lon = float(st.session_state.get(LON_K, 7.73000))
    label = st.session_state.get(LAB_K, "🇮🇹  Champoluc, Valle d’Aosta — IT")

    # input
    q = st.text_input(ph, key=Q_K, value=st.session_state.get(Q_K, ""), placeholder=ph)

    # cerca se q >= 2 char
    options: List[str] = []
    st.session_state.setdefault(OPTS_K, {})
    if q and len(q.strip()) >= 2:
        try:
            a = _om_geocode(q.strip(), iso2, lang_ui)
        except Exception:
            a = []
        try:
            b = _osm_geocode(q.strip(), iso2, lang_ui)
        except Exception:
            b = []
        merged = _merge_results(a, b)

        st.session_state[OPTS_K] = {}
        for it in merged:
            token = f"om|{it['lat']:.6f}|{it['lon']:.6f}|{it['cc']}"
            st.session_state[OPTS_K][token] = it
            options.append(f"{token}  {it['label']}")

    # select risultati
    if options:
        prev = st.session_state.get(SEL_K)
        idx = options.index(prev) if prev in options else 0
        selected_display = st.selectbox("Risultati", options=options, index=idx, key=SEL_K)
        if selected_display:
            token = selected_display.split("  ", 1)[0].strip()
            info = (st.session_state.get(OPTS_K) or {}).get(token)
            if info:
                lat = float(info["lat"]); st.session_state[LAT_K] = lat
                lon = float(info["lon"]); st.session_state[LON_K] = lon
                label = info["label"];    st.session_state[LAB_K] = label

    # badge riassunto
    st.markdown(f"<div class='badge'>📍 {label} · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>", unsafe_allow_html=True)
    return lat, lon, label
