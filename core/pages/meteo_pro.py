# core/pages/meteo_pro.py
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

import pandas as pd
import altair as alt
import streamlit as st

from core import meteo as meteo_mod


def _ensure_race_datetime(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx = dict(ctx or {})
    rd = ctx.get("race_datetime")
    if isinstance(rd, str):
        try:
            ctx["race_datetime"] = datetime.fromisoformat(rd)
        except Exception:
            pass
    return ctx


def _build_profile_df(ctx: Dict[str, Any]):
    ctx = _ensure_race_datetime(ctx)
    profile = meteo_mod.build_meteo_profile_for_race_day(ctx)
    if profile is None:
        return None

    df = pd.DataFrame(
        {
            "time": profile.times,
            "temp_air": profile.temp_air,
            "snow_temp": profile.snow_temp,
            "rh": profile.rh,
            "cloudcover": profile.cloudcover,
            "windspeed": profile.windspeed,
            "precipitation": profile.precip,
            "snowfall": profile.snowfall,
            "shade_index": profile.shade_index,
            "snow_moisture_index": profile.snow_moisture_index,
            "glide_index": profile.glide_index,
        }
    )
    return df


def render_page(T, ctx: Dict[str, Any] | None = None):
    """Dashboard Meteo PRO per la località / gara passata nel ctx."""
    ctx = dict(ctx or {})

    st.header("🌡️ Meteo PRO")

    if "lat" not in ctx or "lon" not in ctx:
        st.info(
            "Nessun contesto meteo salvato. "
            "Torna nella sezione *Località & Mappa* o *Racing / Calendari* "
            "e clicca su **Apri Meteo PRO**."
        )
        return

    lat = float(ctx.get("lat"))
    lon = float(ctx.get("lon"))
    rd = ctx.get("race_datetime")
    if isinstance(rd, str):
        try:
            rd = datetime.fromisoformat(rd)
        except Exception:
            rd = None

    st.markdown(
        f"**Lat/Lon:** {lat:.4f}, {lon:.4f}<br>"
        f"**Data/ora riferimento:** {rd or 'non specificata'}",
        unsafe_allow_html=True,
    )

    df = _build_profile_df(ctx)
    if df is None or df.empty:
        st.warning("Impossibile costruire il profilo meteo per questo contesto.")
        return

    st.caption("Andamento completo 00–24 per la località/ora selezionata.")
    df_reset = df.copy()

    # ---- grafici principali ----
    temp_long = df_reset.melt(
        id_vars="time",
        value_vars=["temp_air", "snow_temp"],
        var_name="series",
        value_name="value",
    )
    chart_temp = (
        alt.Chart(temp_long)
        .mark_line()
        .encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("value:Q", title=None),
            color=alt.Color("series:N", title=None),
            tooltip=[],
        )
        .properties(height=180)
    )

    chart_rh = (
        alt.Chart(df_reset)
        .mark_line()
        .encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("rh:Q", title=None),
            tooltip=[],
        )
        .properties(height=180)
    )

    chart_shade = (
        alt.Chart(df_reset)
        .mark_line()
        .encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("shade_index:Q", title=None),
            tooltip=[],
        )
        .properties(height=180)
    )

    chart_glide = (
        alt.Chart(df_reset)
        .mark_line()
        .encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("glide_index:Q", title=None),
            tooltip=[],
        )
        .properties(height=180)
    )

    wind_long = df_reset.melt(
        id_vars="time",
        value_vars=["windspeed", "cloudcover"],
        var_name="series",
        value_name="value",
    )
    chart_wind_cloud = (
        alt.Chart(wind_long)
        .mark_line()
        .encode(
            x=alt.X("time:T", title=None),
            y=alt.Y("value:Q", title=None),
            color=alt.Color("series:N", title=None),
            tooltip=[],
        )
        .properties(height=200)
    )

    c_a, c_b = st.columns(2)
    with c_a:
        st.markdown("**Temperatura aria vs neve**")
        st.altair_chart(chart_temp, use_container_width=True)

        st.markdown("**Umidità relativa (%)**")
        st.altair_chart(chart_rh, use_container_width=True)
    with c_b:
        st.markdown("**Indice ombreggiatura**")
        st.altair_chart(chart_shade, use_container_width=True)

        st.markdown("**Indice scorrevolezza teorica**")
        st.altair_chart(chart_glide, use_container_width=True)

    st.markdown("**Vento (km/h) e copertura nuvolosa (%)**")
    st.altair_chart(chart_wind_cloud, use_container_width=True)
