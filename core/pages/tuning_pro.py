# core/pages/tuning_pro.py
# Telemark · Pro Wax & Tune — Tuning Dinamico PRO
#
# Vista dedicata SOLO al tuning:
# - Usa il motore meteo (build_meteo_profile_for_race_day)
# - Calcola il tuning dinamico per disciplina / livello / pista iniettata
# - Può usare il contesto Race Day (se presente) oppure input manuali

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import altair as alt
import pandas as pd
import streamlit as st

from core.i18n import L
from core.meteo import (
    build_meteo_profile_for_race_day,
    build_dynamic_tuning_for_race,
)
from core.race_tuning import (
    Discipline,
    SkierLevel,
    SnowType,
    get_tuning_recommendation,
)


# -------------------------------------------------------------
# CONFIG PAGINA
# -------------------------------------------------------------
st.set_page_config(
    page_title="Tuning Dinamico PRO",
    page_icon="🎯",
    layout="wide",
)

# lingua come nello streamlit_app
lang = st.session_state.get("lang", "IT")
T = L["it"] if lang == "IT" else L["en"]

st.title("🎯 Tuning Dinamico PRO")
st.caption("Angoli, struttura, wax e VLT basati su meteo reale e profilo neve.")


# -------------------------------------------------------------
# CONTEXT DI PARTENZA (se arrivo da Race Day / Località)
# -------------------------------------------------------------
ctx_race: Dict[str, Any] = st.session_state.get("race_day_ctx", {}) or {}
ctx_meteo: Dict[str, Any] = st.session_state.get("meteo_pro_ctx", {}) or {}

# Priorità: contesto gara → contesto meteo → default Champoluc / ora attuale
base_ctx = ctx_race if ctx_race else ctx_meteo

default_lat = float(base_ctx.get("lat", 45.833333))
default_lon = float(base_ctx.get("lon", 7.733333))

default_dt = base_ctx.get("race_datetime", datetime.now())
if isinstance(default_dt, str):
    try:
        default_dt = datetime.fromisoformat(default_dt)
    except Exception:
        default_dt = datetime.now()

default_provider = base_ctx.get("provider", "auto")

# disciplina e livello: se arrivo da race_day_ctx li leggo, altrimenti default
disc_default = Discipline.GS
disc_name = base_ctx.get("discipline")
if isinstance(disc_name, str):
    for d in Discipline:
        if d.name == disc_name or d.value == disc_name:
            disc_default = d
            break

level_default = SkierLevel.EXPERT
level_name = base_ctx.get("skier_level")
if isinstance(level_name, str):
    for lv in SkierLevel:
        if lv.name == level_name:
            level_default = lv
            break

injected_default = bool(base_ctx.get("injected", False))


# -------------------------------------------------------------
# INPUT UTENTE
# -------------------------------------------------------------
st.subheader("📍 Setup località, orario e profilo sciatore")

col1, col2, col3 = st.columns(3)

with col1:
    lat = st.number_input("Latitudine", value=default_lat, format="%.6f")
    lon = st.number_input("Longitudine", value=default_lon, format="%.6f")

with col2:
    race_dt = st.datetime_input("Data/Ora riferimento (gara / sciata)", value=default_dt)
    provider = st.selectbox(
        "Provider meteo",
        ["auto", "meteoblue", "open-meteo"],
        index=0 if default_provider not in ["meteoblue", "open-meteo"] else ["auto", "meteoblue", "open-meteo"].index(default_provider),
    )

with col3:
    discipline = st.selectbox(
        "Disciplina",
        list(Discipline),
        index=list(Discipline).index(disc_default),
    )
    skier_level = st.selectbox(
        "Livello sciatore",
        list(SkierLevel),
        index=list(SkierLevel).index(level_default),
    )
    injected = st.checkbox("Pista iniettata / ghiacciata", value=injected_default)


st.divider()
st.subheader("📡 Profilo meteo & neve per il tuning")

# -------------------------------------------------------------
# PROFILO METEO
# -------------------------------------------------------------
profile = build_meteo_profile_for_race_day(
    {
        "lat": lat,
        "lon": lon,
        "race_datetime": race_dt,
        "provider": provider,
    }
)

if profile is None:
    st.error("Impossibile costruire il profilo meteo per questo punto e orario.")
    st.stop()

# DataFrame base
df = pd.DataFrame(
    {
        "time": profile.times,
        "temp_air": profile.temp_air,
        "snow_temp": profile.snow_temp,
        "rh": profile.rh,
        "cloudcover": profile.cloudcover,
        "windspeed": profile.windspeed,
        "precip": profile.precip,
        "snowfall": profile.snowfall,
        "shade": profile.shade_index,
        "moisture": profile.snow_moisture_index,
        "glide": profile.glide_index,
    }
)


# -------------------------------------------------------------
# CALCOLO TUNING DINAMICO
# -------------------------------------------------------------
result = build_dynamic_tuning_for_race(
    profile=profile,
    ctx={"race_datetime": race_dt},
    discipline=discipline,
    skier_level=skier_level,
    injected=injected,
)

if result is None:
    st.error("Errore nella costruzione del tuning dinamico.")
    st.stop()

# Raccomandazione lamina / struttura / wax
rec = get_tuning_recommendation(result.input_params)
side_angle_deg = 90.0 - rec.side_bevel_deg  # 87/88 ecc.


# -------------------------------------------------------------
# BOX RIASSUNTO TUNING
# -------------------------------------------------------------
st.subheader("🎯 Tuning consigliato per l’orario scelto")

c1, c2, c3 = st.columns(3)

with c1:
    st.metric(
        "Neve superficie",
        f"{result.input_params.snow_temp_c:.1f} °C",
    )
    st.metric(
        "Aria",
        f"{result.input_params.air_temp_c:.1f} °C",
    )

with c2:
    snow_type: SnowType = result.snow_type
    snow_type_name = getattr(snow_type, "name", str(snow_type))
    st.metric("Tipo neve", snow_type_name)
    st.metric(
        "Umidità neve (indice)",
        f"{result.input_params.moisture_index:.2f}",
    )

with c3:
    st.metric(
        "Angolo lamina (side)",
        f"{side_angle_deg:.1f}°",
    )
    st.metric(
        "Base bevel",
        f"{rec.base_bevel_deg:.1f}°",
    )

c4, c5, c6 = st.columns(3)

with c4:
    st.metric(
        "Profilo rischio",
        rec.risk_level.capitalize(),
    )

with c5:
    st.metric(
        "VLT consigliata",
        f"{result.vlt_pct:.0f} %",
        help=result.vlt_label,
    )

with c6:
    st.metric(
        "Glide index",
        f"{result.input_params.glide_index:.2f}",
    )

st.markdown(
    f"- **Struttura soletta**: {rec.structure_pattern}\n"
    f"- **Wax group**: {rec.wax_group}\n"
    f"- **Note edges**: {rec.notes}\n"
)
st.info(result.summary)


# -------------------------------------------------------------
# FINESTRA METEO INTORNO ALL’ORARIO RIFERIMENTO
# -------------------------------------------------------------
st.divider()
st.subheader("⏱️ Finestra meteo intorno all’orario scelto")

from datetime import timedelta as _td

start_window = race_dt - _td(hours=3)
end_window = race_dt + _td(hours=3)

mask = (df["time"] >= start_window) & (df["time"] <= end_window)
df_window = df[mask].copy()

if df_window.empty:
    st.warning("Non ci sono dati ±3h rispetto all’orario scelto. Mostro tutta la giornata.")
    df_window = df.copy()

st.dataframe(
    df_window[
        [
            "time",
            "temp_air",
            "snow_temp",
            "windspeed",
            "rh",
            "precip",
            "snowfall",
            "shade",
            "moisture",
            "glide",
        ]
    ].style.format(
        {
            "temp_air": "{:.1f}",
            "snow_temp": "{:.1f}",
            "windspeed": "{:.0f}",
            "rh": "{:.0f}",
            "precip": "{:.1f}",
            "snowfall": "{:.1f}",
            "shade": "{:.2f}",
            "moisture": "{:.2f}",
            "glide": "{:.2f}",
        }
    ),
    use_container_width=True,
)


# -------------------------------------------------------------
# GRAFICI COMPATTI PER IL TUNING
# -------------------------------------------------------------
st.subheader("📈 Temperatura, vento e indici neve")

colT, colW = st.columns(2)

with colT:
    temp_chart = (
        alt.Chart(df_window)
        .transform_fold(
            ["temp_air", "snow_temp"],
            as_=["variable", "value"],
        )
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("time:T", title="Orario"),
            y=alt.Y("value:Q", title="Temperatura (°C)"),
            color=alt.Color("variable:N", title="Serie"),
            tooltip=["time:T", "variable:N", "value:Q"],
        )
        .properties(height=260)
    )
    st.altair_chart(temp_chart, use_container_width=True)

with colW:
    wind_chart = (
        alt.Chart(df_window)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x="time:T",
            y=alt.Y("windspeed:Q", title="Vento (km/h)"),
            tooltip=["time:T", "windspeed:Q"],
        )
        .properties(height=260)
    )
    st.altair_chart(wind_chart, use_container_width=True)

ind_chart = (
    alt.Chart(df_window)
    .transform_fold(
        ["moisture", "glide", "shade"],
        as_=["variable", "value"],
    )
    .mark_line(point=True)
    .encode(
        x="time:T",
        y=alt.Y("value:Q", title="Indice (0–1)"),
        color="variable:N",
        tooltip=["time:T", "variable:N", "value:Q"],
    )
    .properties(height=260)
)

st.altair_chart(ind_chart, use_container_width=True)


# -------------------------------------------------------------
# EXPORT DATI TUNING
# -------------------------------------------------------------
st.divider()
st.subheader("📥 Export dati per questa finestra")

csv = df_window.to_csv(index=False)
st.download_button(
    "Scarica CSV tuning-window",
    data=csv,
    file_name="tuning_dinamico_window.csv",
    mime="text/csv",
  )
