# core/pages/race_day_pro.py
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

import pandas as pd
import altair as alt
import streamlit as st

from core import meteo as meteo_mod
from core.race_tuning import (
    Discipline,
    SkierLevel as TuneSkierLevel,
    get_tuning_recommendation,
)


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


def _parse_discipline(val) -> Discipline:
    if isinstance(val, Discipline):
        return val
    if isinstance(val, str):
        try:
            return Discipline[val]
        except KeyError:
            pass
    return Discipline.GS


def _parse_skier_level(val) -> TuneSkierLevel:
    if isinstance(val, TuneSkierLevel):
        return val
    if isinstance(val, str):
        try:
            return TuneSkierLevel[val]
        except KeyError:
            pass
    return TuneSkierLevel.EXPERT


def render_page(T, ctx: Dict[str, Any] | None = None):
    """Race Day PRO: meteo + tuning dinamico per il contesto gara salvato."""
    ctx = dict(ctx or {})

    st.header("🏁 Race Day PRO")

    if "lat" not in ctx or "lon" not in ctx:
        st.info(
            "Nessun contesto gara salvato. "
            "Torna nella sezione *Racing / Calendari* e clicca su "
            "**Apri Race Day PRO per questa gara**."
        )
        return

    ctx = _ensure_race_datetime(ctx)
    lat = float(ctx.get("lat"))
    lon = float(ctx.get("lon"))
    rd = ctx.get("race_datetime")

    st.markdown(
        f"**Lat/Lon:** {lat:.4f}, {lon:.4f}<br>"
        f"**Data/ora gara:** {rd or 'non specificata'}",
        unsafe_allow_html=True,
    )

    disc = _parse_discipline(ctx.get("discipline"))
    skier_level = _parse_skier_level(ctx.get("skier_level"))
    injected = bool(ctx.get("injected", False))

    # ---- PROFILO METEO ----
    df = _build_profile_df(ctx)
    if df is None or df.empty:
        st.warning("Impossibile costruire il profilo meteo per questa gara.")
        return

    df_reset = df.reset_index(drop=True)

    st.subheader("📈 Meteo & profilo giornata gara")
    st.caption("Andamento 00–24 per la località di gara.")

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

    c_a, c_b = st.columns(2)
    with c_a:
        st.markdown("**Temperatura aria vs neve**")
        st.altair_chart(chart_temp, use_container_width=True)
    with c_b:
        st.markdown("**Umidità relativa (%)**")
        st.altair_chart(chart_rh, use_container_width=True)

    # ---- TUNING DINAMICO ----
    st.subheader("🎯 Tuning dinamico gara")

    dyn = meteo_mod.build_dynamic_tuning_for_race(
        profile=meteo_mod.build_meteo_profile_for_race_day(ctx),
        ctx=ctx,
        discipline=disc,
        skier_level=skier_level,
        injected=injected,
    )

    if dyn is None:
        st.info("Non è stato possibile calcolare il tuning dinamico per questa gara.")
        return

    rec = get_tuning_recommendation(dyn.input_params)
    side_angle = 90.0 - rec.side_bevel_deg

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Disciplina", disc.name)
    c2.metric("Angolo lamina (side)", f"{side_angle:.1f}°")
    c3.metric("Base bevel", f"{rec.base_bevel_deg:.1f}°")
    c4.metric("Profilo", rec.risk_level.capitalize())

    st.markdown(
        f"- **Neve stimata gara**: {dyn.input_params.snow_temp_c:.1f} °C "
        f"({dyn.snow_type.value})\n"
        f"- **Aria all'ora di gara**: {dyn.input_params.air_temp_c:.1f} °C\n"
        f"- **Struttura soletta**: {rec.structure_pattern}\n"
        f"- **Wax group**: {rec.wax_group}\n"
        f"- **VLT consigliata**: {dyn.vlt_pct:.0f}% ({dyn.vlt_label})\n"
        f"- **Note edges**: {rec.notes}\n"
    )

    st.caption(dyn.summary)
