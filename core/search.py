# core/search.py
# Modulo ricerca località: Nominatim + Open-Meteo fallback, caching, retry
import time, math, requests
import streamlit as st
from streamlit_searchbox import st_searchbox

# ---------- Paesi (prefiltro) ----------
COUNTRIES = {
    "Italia": "IT", "Svizzera": "CH", "Francia": "FR", "Austria": "AT",
    "Germania": "DE", "Spagna": "ES", "Norvegia": "NO", "Svezia": "SE"
}

UA = {"User-Agent": "telemark-wax-pro/1.1"}

def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr: dict, fallback: str) -> str:
    name = (addr.get("neighbourhood") or addr.get("hamlet") or addr.get("village")
            or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("state") or addr.get("region") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    s = ", ".join([p for p in [name, admin1] if p])
    return f"{s} — {cc}" if cc else s

def _retry(func, attempts=3, sleep=0.5):
    for i in range(attempts):
        try:
            return func()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(sleep * (1.6 ** i))

# ---------- Data sources ----------
@st.cache_data(ttl=60*60, show_spinner=False)
def nominatim_search_api(q: str, iso2: str):
    r = _retry(lambda: requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": q, "format": "json", "limit": 12, "addressdetails": 1,
                "countrycodes": iso2.lower() if iso2 else None},
        headers=UA, timeout=8
    ))
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=60*60, show_spinner=False)
def openmeteo_geocode_api(q: str, iso2: str):
    # Fallback molto veloce e con toponimi alpini (Courmayeur incluso)
    r = _retry(lambda: requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": q, "language": "it", "count": 10, "format": "json",
                "filter": "country", "country": iso2.upper() if iso2 else None},
        headers=UA, timeout=8
    ))
    r.raise_for_status()
    return r.json()

def _options_from_nominatim(js):
    out = []
    for it in js or []:
        addr = it.get("address", {}) or {}
        lab = concise_label(addr, it.get("display_name", ""))
        cc = addr.get("country_code", "")
        lab = f"{flag(cc)}  {lab}"
        lat = float(it.get("lat", 0)); lon = float(it.get("lon", 0))
        key = f"osm|{lat:.6f}|{lon:.6f}|{lab}"
        out.append({"key": key, "lat": lat, "lon": lon, "label": lab, "source": "osm"})
    return out

def _options_from_openmeteo(js):
    out = []
    for it in (js or {}).get("results", []) or []:
        cc = (it.get("country_code") or "").upper()
        name = it.get("name") or ""
        admin1 = it.get("admin1") or it.get("admin2") or ""
        lab = f"{flag(cc)}  {name}, {admin1} — {cc}".strip().replace(" ,", ",")
        lat = float(it.get("latitude", 0)); lon = float(it.get("longitude", 0))
        key = f"om|{lat:.6f}|{lon:.6f}|{lab}"
        out.append({"key": key, "lat": lat, "lon": lon, "label": lab, "source": "om"})
    return out

# ---------- UI helpers ----------
def country_selectbox(T):
    sel = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
    return COUNTRIES[sel]

def location_searchbox(T, iso2):
    """
    Renderizza lo searchbox e salva la selezione in st.session_state:
    keys: lat, lon, place_label, place_source
    Ritorna il dict della selezione (o None).
    """
    st.session_state.setdefault("_search_options", {})

    def provider(query: str):
        if not query or len(query.strip()) < 2:
            return []
        q = query.strip()
        # 1) Nominatim (preciso su numeri civici)
        try:
            js1 = nominatim_search_api(q, iso2)
            opts1 = _options_from_nominatim(js1)
        except Exception:
            opts1 = []
        # 2) Open-Meteo Geocoding (veloce su toponimi montani — es. Courmayeur)
        try:
            js2 = openmeteo_geocode_api(q, iso2)
            opts2 = _options_from_openmeteo(js2)
        except Exception:
            opts2 = []
        # merge evitando duplicati (lat/lon)
        merged = []
        seen = set()
        for src in (opts1 + opts2):
            k = (round(src["lat"], 5), round(src["lon"], 5))
            if k in seen:
                continue
            seen.add(k)
            merged.append(src)
        # mappa chiave -> oggetto per recupero dopo la scelta
        st.session_state["_search_options"] = {it["key"]: it for it in merged}
        # valori mostrati nella tendina
        return [it["key"] for it in merged]

    # searchbox
    selected_key = st_searchbox(
        provider,
        key="place",
        placeholder=T["search_ph"],
        clear_on_submit=False,
        default=None
    )

    if selected_key and selected_key in st.session_state["_search_options"]:
        info = st.session_state["_search_options"][selected_key]
        st.session_state["lat"] = info["lat"]
        st.session_state["lon"] = info["lon"]
        st.session_state["place_label"] = info["label"]
        st.session_state["place_source"] = info["source"]
        return info

    # default (Champoluc) la prima volta
    if "lat" not in st.session_state:
        st.session_state["lat"] = 45.83333
        st.session_state["lon"] = 7.73333
        st.session_state["place_label"] = "🇮🇹  Champoluc-Champlan, Valle d’Aosta — IT"
        st.session_state["place_source"] = "default"
        return {
            "lat": st.session_state["lat"],
            "lon": st.session_state["lon"],
            "label": st.session_state["place_label"],
            "source": st.session_state["place_source"],
        }

    # niente selezione nuova
    return None

def get_current_selection():
    if "lat" in st.session_state and "place_label" in st.session_state:
        return {
            "lat": float(st.session_state["lat"]),
            "lon": float(st.session_state["lon"]),
            "label": st.session_state["place_label"],
            "source": st.session_state.get("place_source", "state"),
        }
    return None
