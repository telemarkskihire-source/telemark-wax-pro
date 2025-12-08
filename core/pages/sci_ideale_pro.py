# core/pages/sci_ideale_pro.py
# Telemark · Pro Wax & Tune — Sci ideale PRO
#
# Usa:
#   - st.session_state["_meteo_res"]  (DataFrame meteo locale dalla pagina principale)
#   - st.session_state["ref_day"]     (data di riferimento)
#
# e la logica di selezione:
#   - core.pages.ski_selector.recommend_skis_for_day

from __future__ import annotations

from typing import Any, Dict

import pandas as pd
import streamlit as st

from core.i18n import L
from core.pages.ski_selector import recommend_skis_for_day
from core import wax_logic as wax_mod


# -------------------------------------------------------------
# CONFIG PAGINA
# -------------------------------------------------------------
st.set_page_config(
    page_title="Sci ideale PRO",
    page_icon="🎿",
    layout="wide",
)

# lingua come nello streamlit_app
lang = st.session_state.get("lang", "IT")
T = L["it"] if lang == "IT" else L["en"]

st.title("🎿 Sci ideale PRO")
st.caption("Suggerimenti modelli multi-marca in base a livello, uso e condizione neve reale.")


# -------------------------------------------------------------
# LETTURA CONTESTO METEO DALLA HOME
# -------------------------------------------------------------
meteo_df = st.session_state.get("_meteo_res")
ref_day = st.session_state.get("ref_day")

if meteo_df is None or ref_day is None:
    st.error(
        "Mancano i dati meteo di contesto.\n\n"
        "Torna alla pagina principale **'Località & Mappa'**, "
        "seleziona una località e un giorno, poi rientra qui."
    )
    st.stop()

if isinstance(meteo_df, pd.DataFrame):
    wax_df = meteo_df.copy()
else:
    wax_df = pd.DataFrame(meteo_df)


# -------------------------------------------------------------
# SCELTA ORARIO DI RIFERIMENTO + CALCOLO CONDIZIONE NEVE
# -------------------------------------------------------------
st.subheader("🕒 Condizione neve al momento scelto")

col_d, col_t = st.columns(2)
with col_d:
    st.write(f"Giorno di riferimento: **{ref_day.strftime('%Y-%m-%d')}**")

with col_t:
    ref_time = st.time_input(
        "Orario di riferimento (inizio sciata)",
        value=st.session_state.get("free_ref_time", None),
        key="ski_pro_ref_time",
    )

if ref_time is None:
    st.warning("Seleziona un orario per valutare la condizione neve.")
    st.stop()

from datetime import datetime as _dt

ts_ref = _dt.combine(ref_day, ref_time)

# wax_df ha una colonna "time_local" (dalla pagina principale)
if "time_local" not in wax_df.columns:
    st.error("Formato _meteo_res inatteso: manca la colonna 'time_local'.")
    st.stop()

idx = (wax_df["time_local"] - ts_ref).abs().idxmin()
row_ref = wax_df.loc[idx]

snow_label = wax_mod.classify_snow(row_ref)

st.markdown(
    f"<div class='card small'>"
    f"<b>Condizione neve stimata alle {ref_time.strftime('%H:%M')}</b>: "
    f"{snow_label} · T neve ~ {row_ref['T_surf']:.1f} °C · "
    f"UR ~ {row_ref['RH']:.0f}%</div>",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------
# INPUT UTENTE: LIVELLO + USO
# -------------------------------------------------------------
st.divider()
st.subheader("👤 Profilo sciatore & uso principale")

col_l, col_u = st.columns(2)

with col_l:
    ski_level_label = st.selectbox(
        "Livello sciatore",
        [
            ("Principiante", "beginner"),
            ("Intermedio", "intermediate"),
            ("Avanzato", "advanced"),
            ("Race / agonista", "race"),
        ],
        index=1,
        format_func=lambda x: x[0],
        key="ski_pro_level",
    )

with col_u:
    usage_pref = st.selectbox(
        "Uso principale",
        [
            "Pista allround",
            "SL / raggi stretti",
            "GS / raggi medi",
            "All-mountain",
            "Freeride",
            "Skialp / touring",
        ],
        index=0,
        key="ski_pro_usage",
    )

chosen_level_tag = ski_level_label[1]


# -------------------------------------------------------------
# RACCOMANDAZIONE MODELLI
# -------------------------------------------------------------
st.divider()
st.subheader("✅ Modelli consigliati per oggi")

skis = recommend_skis_for_day(
    level_tag=chosen_level_tag,
    usage_pref=usage_pref,
    snow_label=snow_label,
)

if not skis:
    st.info("Nessun modello suggerito per questi filtri (lista interna vuota).")
else:
    for ski in skis:
        st.markdown(
            f"<div class='card small'>"
            f"<b>{ski.brand} · {ski.model}</b><br>"
            f"Categoria: {ski.usage} · Focus neve: {ski.snow_focus}<br>"
            f"{ski.notes}"
            f"</div>",
            unsafe_allow_html=True,
        )

st.caption(
    "Database interno dimostrativo — in futuro qui potremo collegare i tuoi stock reali di sci Telemark."
)
