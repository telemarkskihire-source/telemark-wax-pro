# streamlit_app.py
# Telemark · Pro Wax & Tune — main minimale: tema + ricerca località (core.search)

import os
import streamlit as st
from datetime import date

# === Import moduli core (ATTENZIONE: cartella 'core' deve essere minuscola) ===
from core.i18n import L
try:
    # ci aspettiamo una funzione render(...) che restituisce dict con lat, lon, label, country_name
    from core.search import render as render_search
except Exception as e:
    render_search = None

# === Tema / pagina ===
PRIMARY = "#06b6d4"; ACCENT = "#f97316"
st.set_page_config(page_title="Telemark · Pro Wax & Tune", page_icon="❄️", layout="wide")

st.markdown(f"""
<style>
:root {{ --bg:#0b0f13; --panel:#121821; --muted:#9aa4af; --fg:#e5e7eb; --line:#1f2937; }}
html, body, .stApp {{ background:var(--bg); color:var(--fg); }}
[data-testid="stHeader"] {{ background:transparent; }}
section.main > div {{ padding-top: .6rem; }}
h1,h2,h3,h4 {{ color:#fff; letter-spacing:.2px }}
hr {{ border:none; border-top:1px solid var(--line); margin:.75rem 0 }}
.badge {{ display:inline-flex; align-items:center; gap:.5rem; background:#0b1220; border:1px solid #203045;
         color:#cce7f2; border-radius:12px; padding:.35rem .6rem; font-size:.9rem; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:.9rem .95rem; }}
</style>
""", unsafe_allow_html=True)

# === Lingua (solo switch: IT / EN) ===
st.sidebar.markdown("### ⚙️")
lang = st.sidebar.selectbox(f"{L['it']['lang']} / {L['en']['lang']}", ["IT","EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]

st.title("Telemark · Pro Wax & Tune")

# === Stato iniziale ===
if "lat" not in st.session_state: st.session_state["lat"] = 45.83333
if "lon" not in st.session_state: st.session_state["lon"] = 7.73333
if "place_label" not in st.session_state:
    st.session_state["place_label"] = "🇮🇹  Champoluc, Valle d’Aosta — IT"
if "country_sel" not in st.session_state: st.session_state["country_sel"] = "Italia"

# === BLOCCO 1: Ricerca località (delegato a core.search) ===
st.subheader(f"1) {T['search_ph']}")
if render_search is None:
    st.error("Modulo core.search non disponibile o errore di import. Controlla che la cartella si chiami 'core' e contenga search.py con funzione render(...).")
else:
    # L'interfaccia attesa del modulo: render(lang:str, default_country:str, state:dict) -> dict
    # Deve restituire: {'lat':float,'lon':float,'label':str,'country_name':str}
    result = render_search(lang=lang, default_country=st.session_state["country_sel"], state=dict(
        lat=st.session_state["lat"],
        lon=st.session_state["lon"],
        label=st.session_state["place_label"],
        country_name=st.session_state["country_sel"],
    ))

    if isinstance(result, dict):
        st.session_state["lat"] = float(result.get("lat", st.session_state["lat"]))
        st.session_state["lon"] = float(result.get("lon", st.session_state["lon"]))
        st.session_state["place_label"] = result.get("label", st.session_state["place_label"])
        st.session_state["country_sel"] = result.get("country_name", st.session_state["country_sel"])

# Badge di conferma selezione corrente
st.markdown(
    f"<div class='badge'>📍 <b>{st.session_state['place_label']}</b> · "
    f"lat <b>{st.session_state['lat']:.5f}</b>, lon <b>{st.session_state['lon']:.5f}</b></div>",
    unsafe_allow_html=True
)

# (Il resto dell'app — meteo, mappe, tabelle — resterà nei moduli core/ e verrà richiamato in step successivi)
