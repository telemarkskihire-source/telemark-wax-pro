# core/maps.py
import requests, time
import streamlit as st
from core.utils import _retry, flag, UA

COUNTRIES = {
    "Italia":"IT","Svizzera":"CH","Francia":"FR","Austria":"AT","Germania":"DE",
    "Spagna":"ES","Norvegia":"NO","Svezia":"SE"
}

@st.cache_data(ttl=3600, show_spinner=False)
def _geocode_openmeteo(q:str, cc:str|None, lang:str):
    # Open-Meteo geocoding: molto rapido, trova bene (Courmayeur incluso)
    params = {"name": q, "count": 15, "language": "it" if lang=="IT" else "en"}
    if cc: params["country"] = cc
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search", params=params, headers=UA, timeout=8)
    if r.status_code != 200: return []
    js = r.json() or {}
    return js.get("results") or []

@st.cache_data(ttl=3600, show_spinner=False)
def _geocode_nominatim(q:str, cc:str|None):
    params = {"q": q, "format":"json", "limit":10, "addressdetails":1}
    if cc: params["countrycodes"] = cc.lower()
    r = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=UA, timeout=10)
    if r.status_code != 200: return []
    return r.json() or []

def place_search_box(T):
    from streamlit_searchbox import st_searchbox

    # selettore paese (prefiltro) – opzionale
    col = st.columns([2,1])
    with col[1]:
        sel_country = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
        iso2 = COUNTRIES[sel_country]
    with col[0]:
        def search_fn(q:str):
            if not q or len(q.strip())<2:
                return []
            q = q.strip()
            # 1) Provo Open-Meteo (veloce)
            om = _geocode_openmeteo(q, iso2, st.session_state.get("lang","IT"))
            out=[]
            for it in om:
                name = it.get("name","")
                admin1 = it.get("admin1") or it.get("country_code") or ""
                cc = (it.get("country_code") or "").upper()
                lab = f"{flag(cc)}  {name}, {admin1} — {cc}" if admin1 else f"{flag(cc)}  {name} — {cc}"
                key = f"om|{it.get('latitude'):.6f}|{it.get('longitude'):.6f}|{lab}"
                out.append(key)
            # 2) Se pochi risultati, fallback Nominatim
            if len(out) < 3:
                try:
                    nm = _geocode_nominatim(q, iso2)
                    for it in nm:
                        cc = (it.get("address",{}).get("country_code","") or "").upper()
                        name = it.get("display_name","").split(",")[0]
                        lab = f"{flag(cc)}  {name} — {cc}" if cc else name
                        key = f"nm|{float(it.get('lat',0)):.6f}|{float(it.get('lon',0)):.6f}|{lab}"
                        out.append(key)
                except Exception:
                    pass
            # dedup mantenendo ordine
            seen=set(); res=[]
            for k in out:
                if k not in seen:
                    seen.add(k); res.append(k)
            return res[:12]

        sel = st_searchbox(
            search_fn,
            key="place_search",
            placeholder=T["search_ph"],
            clear_on_submit=False,
            default=None
        )

    if sel and "|" in sel:
        _, la, lo, lab = sel.split("|", 3)
        return {"lat": float(la), "lon": float(lo), "label": lab}
    return None
