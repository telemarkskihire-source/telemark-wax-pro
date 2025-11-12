# app.py
import streamlit as st
from datetime import date
from core.i18n import L
from core.utils import persist
from core.maps import place_search_box

st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")

st.markdown("""
<style>
:root { --bg:#0b0f13; --panel:#121821; --fg:#e5e7eb; --line:#1f2937; }
html, body, .stApp { background:var(--bg); color:var(--fg); }
[data-testid="stHeader"] { background:transparent; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem }
.badge { display:inline-flex; gap:.5rem; background:#0b1220; border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }
</style>
""", unsafe_allow_html=True)

st.title("Telemark · Pro Wax & Tune")

# Sidebar: lingua / unità (solo lingua qui per semplicità)
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang=="IT" else L["en"]

# --- Ricerca località (veloce) ---
st.subheader("1) " + T["search_ph"])
place = place_search_box(T)  # restituisce dict con lat,lon,label, cc (o None)

# Badge posizione attuale
if place:
    st.session_state["lat"] = place["lat"]
    st.session_state["lon"] = place["lon"]
    st.session_state["place_label"] = place["label"]
else:
    st.session_state.setdefault("lat", 45.831)
    st.session_state.setdefault("lon", 7.730)
    st.session_state.setdefault("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

st.markdown(f"<div class='badge'>📍 <b>{st.session_state['place_label']}</b> · lat {st.session_state['lat']:.5f}, lon {st.session_state['lon']:.5f}</div>", unsafe_allow_html=True)

# --- Placeholder per passi successivi (meteo, mappe, ecc.) ---
st.markdown("—")
st.info("OK: ricerca località separata in modulo. Prossimo step: spostiamo meteo e mappa nei moduli `core/`.")
