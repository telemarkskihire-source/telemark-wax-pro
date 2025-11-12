# core/search.py
import unicodedata, requests, streamlit as st
from streamlit_searchbox import st_searchbox

UA = {"User-Agent": "telemark-wax-pro/1.0", "Accept-Language": "it,en;q=0.8"}

COUNTRIES = {
    "Italia": "IT","Svizzera":"CH","Francia":"FR","Austria":"AT",
    "Germania":"DE","Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}

def _norm(s:str)->str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join([c for c in s if not unicodedata.combining(c)])
    return s.strip()

def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr: dict, fallback: str) -> str:
    name = (addr.get("village") or addr.get("town") or addr.get("city") or
            addr.get("municipality") or fallback)
    admin1 = addr.get("region") or addr.get("state") or addr.get("county") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

# ---------- GEOCODING: Open-Meteo (fast) ----------
@st.cache_data(ttl=6*3600, show_spinner=False)
def _om_geocode(q: str, iso2: str):
    params = {
        "name": q, "count": 12, "language": "it",
        "format": "json", "filter": "city,locality,village,town",
    }
    # bias al paese
    if iso2: params["country"] = iso2.upper()
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params=params, headers=UA, timeout=6)
    r.raise_for_status()
    js = r.json()
    out = []
    for it in js.get("results", []) or []:
        cc = (it.get("country_code") or "").upper()
        lab = f"{it.get('name','')}, {it.get('admin1','')}".strip(", ")
        lab2 = f"{flag(cc)}  {lab}"
        lat, lon = float(it["latitude"]), float(it["longitude"])
        key = f"{lab2}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat":lat,"lon":lon,"label":lab2,"addr":{"country_code":cc}}))
    return out

# ---------- GEOCODING: Nominatim (fallback) ----------
@st.cache_data(ttl=6*3600, show_spinner=False)
def _nominatim_geocode(q: str, iso2: str):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": q, "format":"json", "limit":12, "addressdetails":1,
            "countrycodes": (iso2 or "").lower(), "dedupe": 1
        },
        headers=UA, timeout=8
    )
    r.raise_for_status()
    out=[]
    for it in r.json():
        addr = it.get("address",{}) or {}
        lab  = concise_label(addr, it.get("display_name",""))
        cc   = addr.get("country_code","") or (iso2 or "").lower()
        lab2 = f"{flag(cc)}  {lab}"
        lat  = float(it.get("lat",0)); lon=float(it.get("lon",0))
        key  = f"{lab2}|||{lat:.6f},{lon:.6f}"
        out.append((key, {"lat":lat,"lon":lon,"label":lab2,"addr":addr}))
    return out

def _search_backend(q: str, iso2: str):
    qn = _norm(q)
    if not qn or len(qn) < 2:
        return []
    # se l’utente non ha messo il paese, lo aggiungiamo per aiutare (es. “Courmayeur IT”)
    q_bias = f"{qn} {iso2}" if iso2 and iso2.lower() not in qn.lower() else qn
    try:
        rows = _om_geocode(q_bias, iso2)
        if not rows:
            rows = _nominatim_geocode(q_bias, iso2)
    except Exception:
        rows = []
        try:
            rows = _nominatim_geocode(q_bias, iso2)
        except Exception:
            pass
    # esito -> lista chiavi per st_searchbox
    st.session_state._options = {k:v for k,v in rows}
    return [k for k,_ in rows]

def location_search_ui(T):
    col = st.columns([2,1])
    with col[1]:
        sel_country = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
        iso2 = COUNTRIES[sel_country]
    with col[0]:
        selected = st_searchbox(
            lambda q: _search_backend(q, iso2),
            key="place",
            placeholder=T["search_ph"],
            clear_on_submit=False,
            default=None,
        )
    # applica selezione
    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state._options.get(selected)
        if info:
            st.session_state["lat"] = info["lat"]
            st.session_state["lon"] = info["lon"]
            st.session_state["place_label"] = info["label"]

    # badge (se presente)
    if all(k in st.session_state for k in ["lat","lon","place_label"]):
        st.markdown(
            f"📍 {st.session_state['place_label']} · lat {st.session_state['lat']:.5f}, lon {st.session_state['lon']:.5f}"
        )
