# core/pages/race_day_pro.py
# Telemark · Pro Wax & Tune — Race Day PRO Dashboard (modulo riutilizzabile)
#
# Espone:
#   render_race_day_pro_dashboard(T, ctx=None)
#
# ctx può contenere:
#   {
#       "lat": float,
#       "lon": float,
#       "race_datetime": datetime | iso-string,
#       "discipline": "SL" / "GS" / ... (nome Enum Discipline),
#       "skier_level": "FIS" / "EXPERT" / ... (nome Enum SkierLevel),
#       "injected": True/False,
#       "provider": "auto" / "meteoblue" / "open-meteo"
#   }

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import altair as alt
import pandas as pd
import streamlit as st

from core.meteo import (
    build_meteo_profile_for_race_day,
    build_dynamic_tuning_for_race,
)
from core.race_tuning import (
    Discipline,
    SkierLevel,
    SnowType,
)


def _ctx_to_defaults(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Converte il contesto in valori di default per gli input UI."""
    default_lat = float(ctx.get("lat", 45.833333))
    default_lon = float(ctx.get("lon", 7.733333))

    default_race_dt = ctx.get("race_datetime", datetime.now())
    if isinstance(default_race_dt, str):
        try:
            default_race_dt = datetime.fromisoformat(default_race_dt)
        except Exception:
            default_race_dt = datetime.now()

    # disciplina
    disc_default = Discipline.SL
    disc_name = ctx.get("discipline")
    if isinstance(disc_name, str):
        for d in Discipline:
            if d.name == disc_name:
                disc_default = d
                break

    # livello
    level_default = SkierLevel.EXPERT
    level_name = ctx.get("skier_level")
    if isinstance(level_name, str):
        for lv in SkierLevel:
            if lv.name == level_name:
                level_default = lv
                break

    injected_default = bool(ctx.get("injected", False))
    provider_default = ctx.get("provider", "auto")

    return {
        "lat": default_lat,
        "lon": default_lon,
        "race_dt": default_race_dt,
        "discipline": disc_default,
        "skier_level": level_default,
        "injected": injected_default,
        "provider": provider_default,
    }


def render_race_day_pro_dashboard(
    T: Dict[str, Any],
    ctx: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Renderizza la dashboard Race Day PRO dentro una pagina o tab esistente.

    - Non chiama st.set_page_config
    - Non imposta il titolo globale della pagina
    """

    st.markdown("### 🏁 Race Day PRO — Meteo & Tuning Dinamico")
    st.caption(
        "Vista dedicata al giorno di gara: neve, aria, VLT, vento, tuning completo."
    )

    # ----- contesto di partenza -----
    if ctx is None:
        ctx = st.session_state.get("race_day_ctx", {}) or {}

    defaults = _ctx_to_defaults(ctx)

    # -------------------------------------------------------------
    # INPUT UTENTE (precompilati se arriva il contesto)
    # -------------------------------------------------------------
    col1, col2, col3 = st.columns(3)

    with col1:
        lat = st.number_input("Latitudine", value=defaults["lat"], format="%.6f")
        lon = st.number_input("Longitudine", value=defaults["lon"], format="%.6f")

    with col2:
        race_dt = st.datetime_input(
            "Data/Ora gara (start)",
            value=defaults["race_dt"],
        )
        provider = st.selectbox(
            "Provider meteo",
            ["auto", "meteoblue", "open-meteo"],
            index=["auto", "meteoblue", "open-meteo"].index(
                defaults.get("provider", "auto")
                if defaults.get("provider", "auto") in ["auto", "meteoblue", "open-meteo"]
                else "auto"
            ),
        )

    with col3:
        discipline = st.selectbox(
            "Disciplina",
            list(Discipline),
            index=list(Discipline).index(defaults["discipline"]),
        )
        skier_level = st.selectbox(
            "Livello sciatore",
            list(SkierLevel),
            index=list(SkierLevel).index(defaults["skier_level"]),
        )
        injected = st.checkbox(
            "Pista iniettata (ghiaccio)",
            value=defaults["injected"],
        )

    st.divider()
    st.subheader("📡 Profilo meteo & neve per il giorno di gara")

    profile = build_meteo_profile_for_race_day(
        {
            "lat": lat,
            "lon": lon,
            "race_datetime": race_dt,
            "provider": provider,
        }
    )

    if profile is None:
        st.error("Impossibile costruire un profilo meteo per questa gara.")
        return

    result = build_dynamic_tuning_for_race(
        profile=profile,
        ctx={"race_datetime": race_dt},
        discipline=discipline,
        skier_level=skier_level,
        injected=injected,
    )

    if result is None:
        st.error("Errore nella costruzione del tuning dinamico.")
        return

    # -------------------------------------------------------------
    # DATAFRAME BASE
    # -------------------------------------------------------------
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
    # BOX TUNING
    # -------------------------------------------------------------
    st.subheader("🎯 Tuning dinamico per l’orario gara")

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
        st.metric(
            "Tipo neve",
            snow_type_name,
        )
        st.metric(
            "Umidità neve (indice)",
            f"{result.input_params.moisture_index:.2f}",
        )

    with c3:
        st.metric(
            "VLT consigliata",
            f"{result.vlt_pct:.0f} %",
            help=result.vlt_label,
        )
        st.metric(
            "Glide index",
            f"{result.input_params.glide_index:.2f}",
        )

    st.info(result.summary)

    # -------------------------------------------------------------
    # FOCUS METEO ATTORNO ALL’ORA GARA
    # -------------------------------------------------------------
    st.divider()
    st.subheader("⏱️ Finestra meteo intorno all’ora di partenza")

    start_window = race_dt - timedelta(hours=3)
    end_window = race_dt + timedelta(hours=3)

    mask = (df["time"] >= start_window) & (df["time"] <= end_window)
    df_window = df[mask].copy()

    if df_window.empty:
        st.warning(
            "Non ci sono dati nell’intorno ±3h rispetto all’ora gara. Mostro tutta la giornata."
        )
        df_window = df.copy()

    df_window["delta_min"] = (
        df_window["time"] - race_dt
    ).dt.total_seconds() / 60.0

    st.write("Tabella sintetica intorno alla gara (°C, vento, neve):")
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
    # GRAFICI COMPATTI RACE DAY
    # -------------------------------------------------------------
    st.subheader("📈 Grafici Race Day — Temperatura, Vento, Indici")

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

    st.subheader("🏂 Indici neve nella finestra gara")

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
    # DOWNLOAD REPORT CSV
    # -------------------------------------------------------------
    st.divider()
    st.subheader("📥 Export dati Race Day")

    csv = df_window.to_csv(index=False)
    st.download_button(
        "Scarica CSV finestra gara",
        data=csv,
        file_name="race_day_window.csv",
        mime="text/csv",
    )
