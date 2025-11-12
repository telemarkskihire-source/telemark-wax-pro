# streamlit_app.py
# Telemark · Pro Wax & Tune — skeleton con ricerca località modulare (core/search)

import os, time, requests
import streamlit as st
from core.i18n import L
from core.search import COUNTRIES, country_selectbox, location_searchbox

# ---------- THEME (dark) ----------
PRIMARY = "#06b6d4"; ACCENT = "#f97316"; ERR = "#ef4444"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")
st.markdown("""
<style>
:root { --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }
html, body, .stApp { background:var(--bg); color:var(--fg); }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top: 0.6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
hr { border:none; border-top:1px solid var(--line); margin:.75rem 0 }
.badge { display:inline-flex; align-items:center; gap:.5rem; background:#0b1220;
  border:1px solid #203045; color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.85rem; }
</style>
""", unsafe_allow_html=True)

# ---------- LINGUA ----------
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(L["it"]["lang"]+" / "+L["en"]["lang"], ["IT","EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# ---------- 1) Ricerca località (modularizzata) ----------
st.markdown(f"### 1) {T['search_ph']}")
iso2 = country_selectbox(T)  # select paese (prefiltro)

lat, lon, place_label = location_searchbox(T, iso2)  # searchbox rapido

if lat is not None and lon is not None:
    st.markdown(
        f"<div class='badge'>📍 <b>{place_label}</b> · "
        f"lat <b>{lat:.5f}</b>, lon <b>{lon:.5f}</b></div>",
        unsafe_allow_html=True
    )
else:
    st.info("Digita almeno 2–3 caratteri per vedere i suggerimenti.")

# Nota: nelle prossime iterazioni potrai importare da core/ anche meteo, mappe, tabelle, ecc.
