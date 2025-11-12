# core/search.py
# Ricerca località: provider 1 = Open-Meteo Geocoding (rapido)
# fallback provider 2 = Nominatim (OSM) con pre-filtro paese
# Espone: place_search_ui(T, iso2, key_prefix="place") -> (lat, lon, label)

from __future__ import annotations
import math, time, unicodedata, requests
import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox

# ---------- utils locali (no dipendenze da altri moduli) ----------
UA = {
    "User-Agent": "telemark-wax-pro/1.1 (+https://telemarkskihire.com)"
}

def _flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"

def _concise_label(addr_name: str, admin: str | None, cc: str | None) -> str:
    parts = [p for p in [addr_name, admin] if p]
    s = ", ".join(parts) if parts else addr_name
    return f"{s} — {cc.upper()}" if cc else s

def _norm(s: str) -> str:
    # per dedup: toglie accenti e normalizza
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode().lower().strip()

# ---------- PROVIDER 1: Open-Meteo Geocoding (veloce) ----------
@st.cache_data(ttl=3600, show_spinner=False)
def _om_geocode(name: str, iso2: str, lang: str = "it"):
    params = {
        "name": name,
        "count": 12,
        "language": lang.lower(),
        "format": "json",
        "country": iso2.upper()
    }
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params=params, headers=UA, timeout=8)
    r.raise_for_status()
    j = r.json() or {}
    results = []
    for it in (j.get("results") or []):
        city  = it.get("name") or ""
        admin = it.get("admin1") or it.get("admin2") or it.get("country")
        cc    = it.get("country_code")
        lat   = float(it.get("latitude"))
        lon   = float(it.get("longitude"))
        label = _concise_label(city, admin, cc)
        disp  = f"{_flag(cc or '')}  {label}"
        results.append({
            "label": disp, "lat": lat, "lon": lon, "cc": cc or iso2,
            "raw_label": label
        })
    return results

# ---------- PROVIDER 2: Nominatim (OSM) ----------
@st.cache_data(ttl=3600, show_spinner=False)
def _osm_geocode(name: str, iso2: str, lang: str = "it"):
    params = {
        "q": name,
        "format": "json",
        "limit": 12,
        "addressdetails": 1,
        "accept-language": lang.lower(),
        "countrycodes": iso2.lower()
    }
    r = requests.get("https://nominatim.openstreetmap.org/search",
                     params=params, headers=UA, timeout=10)
    r.raise_for_status()
    out = []
    for it in (r.json() or []):
        addr = it.get("address", {}) or {}
        name0 = (addr.get("village") or addr.get("town") or addr.get("city")
                 or addr.get("hamlet") or it.get("display_name", ""))
        admin = (addr.get("state") or addr.get("region") or addr.get("county"))
        cc    = (addr.get("country_code") or "").upper()
        lat   = float(it.get("lat", 0))
        lon   = float(it.get("lon", 0))
        label = _concise_label(name0, admin, cc)
        disp  = f"{_flag(cc)}  {label}"
        out.append({
            "label": disp, "lat": lat, "lon": lon, "cc": cc or iso2,
            "raw_label": label
        })
    return out

# ---------- merge + dedup ----------
def _merge_results(a, b):
    seen = set()
    out = []
    for src in (a or []), (b or []):
        for it in src:
            key = (_norm(it["raw_label"]), round(it["lat"], 4), round(it["lon"], 4))
            if key in seen: 
                continue
            seen.add(key)
            out.append(it)
    return out

# ---------- callback per st_searchbox ----------
def _search_callback_factory(iso2: str, lang_ui: str):
    def _cb(q: str):
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
        st.session_state.setdefault("_search_opts", {})
        out_strings = []
        for it in merged:
            token = f"om|{it['lat']:.6f}|{it['lon']:.6f}|{it['cc']}"
            st.session_state["_search_opts"][token] = it
            out_strings.append(f"{token}  {it['label']}")
        return out_strings
    return _cb

# ---------- UI wrapper richiamabile dal main ----------
def place_search_ui(T: dict, iso2: str, key_prefix: str = "place"):
    """
    Disegna la searchbox e restituisce (lat, lon, label)
    Aggiorna anche st.session_state['lat'/'lon'/'place_label'].
    """
    # placeholder in base alla lingua
    ph = T.get("search_ph", "Cerca località…")
    # lingua dal dizionario (heuristic: 'it' se contiene parole italiane)
    lang_ui = "it" if "Cerca" in ph or "Nazione" in (T.get("country","")) else "en"

    selected = st_searchbox(
        _search_callback_factory(iso2, lang_ui),
        key=f"{key_prefix}_sb",
        placeholder=ph,
        clear_on_submit=False,
        default=None
    )

    # valore corrente persistito (se già impostato dal main)
    lat = float(st.session_state.get("lat", 45.831))
    lon = float(st.session_state.get("lon", 7.730))
    label = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

    if selected:
        # `selected` è la riga visibile. Il token è sempre in testa: om|lat|lon|CC
        token = selected.split("  ", 1)[0].strip()
        info = (st.session_state.get("_search_opts") or {}).get(token)
        if info:
            lat = float(info["lat"])
            lon = float(info["lon"])
            label = info["label"]
            st.session_state["lat"] = lat
            st.session_state["lon"] = lon
            st.session_state["place_label"] = label

    # badge riassunto (facoltativo, ma comodo)
    st.markdown(
        f"<div class='badge'>📍 {label} · lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True
    )
    return lat, lon, label
