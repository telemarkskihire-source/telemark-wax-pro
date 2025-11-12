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
html, body, .stApp { background:var(--bg); color:#e5e7eb; }
[data-testid="stHeader"] { background:transparent; }
section.main > div { padding-top: 0.6rem; }
h1,h2,h3,h4 { color:#fff; letter-spacing:.2px }
hr { border:none; border-top:1px solid #1f2937; margin:.75rem 0 }
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

# Chiamata TOLLERANTE: non facciamo unpack diretto
_res = location_searchbox(T, iso2)  # può essere (lat,lon,label) oppure chiave stringa oppure None

# Defaults/persistiti (Champoluc)
_lat = float(st.session_state.get("lat", 45.831))
_lon = float(st.session_state.get("lon", 7.730))
_lab = st.session_state.get("place_label", "🇮🇹  Champoluc, Valle d’Aosta — IT")

# 1) Caso tupla valida
if isinstance(_res, tuple) and len(_res) == 3:
    try:
        _lat, _lon, _lab = float(_res[0]), float(_res[1]), str(_res[2])
    except Exception:
        pass
# 2) Caso chiave "label|||lat,lon" risolvibile da _options
elif isinstance(_res, str) and "|||" in _res and "_options" in st.session_state:
    info = (getattr(st.session_state, "_options", {}) or {}).get(_res, {})
    _lat = float(info.get("lat", _lat))
    _lon = float(info.get("lon", _lon))
    _lab = str(info.get("label", _lab))
# 3) Caso None/altro → restano i defaults/persistiti

# Salva comunque in sessione per coerenza
st.session_state["lat"] = _lat
st.session_state["lon"] = _lon
st.session_state["place_label"] = _lab

# Badge
st.markdown(
    f"<div class='badge'>📍 <b>{_lab}</b> · "
    f"lat <b>{_lat:.5f}</b>, lon <b>{_lon:.5f}</b></div>",
    unsafe_allow_html=True
)

# Nota: nelle prossime iterazioni potrai importare da core/ anche meteo, mappe, tabelle, ecc.
