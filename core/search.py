import requests, streamlit as st
from streamlit_searchbox import st_searchbox

UA = {"User-Agent": "telemark-wax-pro/1.0"}

COUNTRIES = {
    "Italia": "IT", "Svizzera": "CH", "Francia": "FR", "Austria": "AT",
    "Germania": "DE", "Spagna": "ES", "Norvegia": "NO", "Svezia": "SE"
}

def flag(cc: str) -> str:
    try:
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except:
        return "🏳️"

def concise_label(addr: dict, fallback: str) -> str:
    name = (addr.get("village") or addr.get("town") or addr.get("city") or fallback)
    admin1 = addr.get("region") or addr.get("state") or ""
    cc = (addr.get("country_code") or "").upper()
    parts = [p for p in [name, admin1] if p]
    s = ", ".join(parts)
    return f"{s} — {cc}" if cc else s

def nominatim_search(q: str, iso2: str):
    if not q or len(q) < 2:
        return []
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 12, "addressdetails": 1, "countrycodes": iso2.lower()},
            headers=UA, timeout=8
        )
        r.raise_for_status()
        st.session_state._options = {}
        out = []
        for it in r.json():
            addr = it.get("address", {}) or {}
            lab = concise_label(addr, it.get("display_name", ""))
            cc = addr.get("country_code", "")
            lab = f"{flag(cc)}  {lab}"
            lat = float(it.get("lat", 0))
            lon = float(it.get("lon", 0))
            key = f"{lab}|||{lat:.6f},{lon:.6f}"
            st.session_state._options[key] = {"lat": lat, "lon": lon, "label": lab, "addr": addr}
            out.append(key)
        return out
    except Exception:
        return []

def location_search_ui(T):
    col_top = st.columns([2, 1])
    with col_top[1]:
        sel_country = st.selectbox(T["country"], list(COUNTRIES.keys()), index=0, key="country_sel")
        iso2 = COUNTRIES[sel_country]
    with col_top[0]:
        selected = st_searchbox(
            lambda q: nominatim_search(q, iso2),
            key="place",
            placeholder=T["search_ph"],
            clear_on_submit=False,
            default=None,
        )
    if selected and "|||" in selected and "_options" in st.session_state:
        info = st.session_state._options.get(selected)
        if info:
            st.session_state["lat"] = info["lat"]
            st.session_state["lon"] = info["lon"]
            st.session_state["place_label"] = info["label"]
    if "place_label" in st.session_state:
        st.markdown(
            f"📍 {st.session_state['place_label']} · lat {st.session_state['lat']:.5f}, lon {st.session_state['lon']:.5f}"
      )
