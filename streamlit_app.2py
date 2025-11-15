# streamlit_app.py
import os
import importlib
import streamlit as st
import pandas as pd

from core.i18n import L
from core.search import location_searchbox
from core.fis_calendar import get_fis_calendar


st.set_page_config(
    page_title="Telemark · Pro Wax & Tune",
    page_icon="❄️",
    layout="wide",
)

# --------------------------
# TEMA
# --------------------------
st.markdown("""
<style>
:root { --bg:#0b0f13; --panel:#121821; --fg:#e5e7eb; --muted:#9aa4af; }
html, body, .stApp { background:var(--bg); color:var(--fg); }
</style>
""", unsafe_allow_html=True)


# --------------------------
# LINGUA
# --------------------------
st.sidebar.markdown("### ⚙️")

lang = st.sidebar.selectbox("Lingua / Language", ["IT", "EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]


# --------------------------
# TABS
# --------------------------
tab_wax, tab_fis = st.tabs(["🧊 Wax & Tune", "🏁 Cup / FIS"])


# --------------------------
# TAB WAX
# --------------------------
with tab_wax:
    st.markdown("### Ricerca località")
    lat, lon, place = location_searchbox(T)
    st.write(f"📍 {place} — {lat:.4f}, {lon:.4f}")


# --------------------------
# TAB FIS
# --------------------------
with tab_fis:
    st.markdown("### Calendario FIS (via Telemark proxy)")

    season = st.number_input("Stagione", 2024, 2035, 2025)

    gender = st.radio("Genere", ["Entrambi", "Uomini", "Donne"])
    gender_code = None
    if gender == "Uomini":
        gender_code = "M"
    elif gender == "Donne":
        gender_code = "W"

    disc = st.selectbox("Disciplina", ["Tutte", "SL", "GS", "SG", "DH", "AC"])
    disc_code = None if disc == "Tutte" else disc

    if st.button("🔍 Carica gare FIS"):
        with st.spinner("Scarico gare dal proxy Telemark..."):
            events = get_fis_calendar(
                season=int(season),
                discipline=disc_code,
                gender=gender_code,
            )

        if not events:
            st.warning("Nessuna gara trovata.")
        else:
            st.success(f"Trovate {len(events)} gare.")

            df = pd.DataFrame(events)
            st.dataframe(df, use_container_width=True)

            labels = [
                f"{ev['date']} · {ev['place']} · {ev['event']}"
                for ev in events
            ]

            idx = st.selectbox("Seleziona gara", range(len(events)),
                               format_func=lambda i: labels[i])

            st.json(events[idx])
