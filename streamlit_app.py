# streamlit_app.py
# Telemark · Pro Wax & Tune + Modalità Gara (Neveitalia)

import sys
import os
import importlib
import streamlit as st

# reload core
importlib.invalidate_caches()
for m in list(sys.modules.keys()):
    if m.startswith("core."):
        del sys.modules[m]

from core.i18n import L
from core.search import location_searchbox
from core.get_calendar import get_fis_worldcup_races
from core.race_integration import get_wc_tuning


# ---------------- UI ----------------

st.set_page_config(page_title="Telemark PRO — Wax & Race", layout="wide")

st.title("Telemark · Pro Wax & Tune")


lang = st.sidebar.selectbox("Lingua", ["IT", "EN"], index=0)
T = L["it"] if lang == "IT" else L["en"]

tab_wax, tab_race = st.tabs(["🧊 Wax & Tune", "🏁 Race"])


# ---------------- TAB 1 ----------------

with tab_wax:
    st.header("Wax & Tune · Località")

    lat, lon, place = location_searchbox(T)
    st.write(f"📍 **{place}**  — lat `{lat}` lon `{lon}`")

    st.info("Qui rimane il tuo modulo meteo + wax + dem + map + pov già implementato.")


# ---------------- TAB 2 (GARE) ----------------

with tab_race:
    st.header("Calendario Gare — FIS World Cup (Neveitalia)")

    col1, col2, col3 = st.columns(3)

    with col1:
        season = st.number_input("Stagione (anno di inizio)", 2024, 2035, 2025)

    with col2:
        gender = st.selectbox("Categoria", ["Maschile (M)", "Femminile (F)", "Entrambi"])

    with col3:
        disc = st.selectbox("Disciplina", ["Tutte", "SL", "GS", "SG", "DH"])

    if gender.startswith("Mas"):
        g = "M"
    elif gender.startswith("Fem"):
        g = "F"
    else:
        g = None

    disc_filter = None if disc == "Tutte" else disc

    if st.button("🔍 Carica gare"):
        st.info("Scarico calendario da Neveitalia...")
        events = get_fis_worldcup_races(
            season=season,
            gender=g,
            discipline=disc_filter
        )

        if not events:
            st.warning("Nessuna gara trovata.")
        else:
            st.success(f"{len(events)} gare trovate")

            sel = st.selectbox(
                "Seleziona gara",
                events,
                format_func=lambda e: f"{e['date']} — {e['location']} — {e['event']}",
            )

            if st.button("🎯 Calcola Tuning WC"):
                res = get_wc_tuning(sel)

                if "error" in res:
                    st.error(res["error"])
                else:
                    st.subheader("Tuning World Cup")
                    st.metric("Base Bevel", f"{res['base_bevel']:.2f}°")
                    st.metric("Side Bevel", f"{res['side_bevel']:.2f}°")
                    st.write(f"**Struttura:** {res['structure']}")
                    st.write(f"**Sciolina:** {res['wax']} — Rischio: **{res['risk']}**")
                    st.write("### Dettagli neve")
                    st.json(res["snow"])

                    st.write("### Evento completo")
                    st.json(res["event"])
