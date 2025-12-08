# core/pages/meteo_pro.py
# Telemark · Pro Wax & Tune — Meteo PRO Dashboard (modulo riutilizzabile)
#
# Espone:
#   render_meteo_pro_dashboard(T, ctx=None)
#
# ctx può contenere:
#   {
#       "lat": float,
#       "lon": float,
#       "race_datetime": datetime | iso-string,
#       "provider": "auto" / "meteoblue" / "open-meteo"
#   }

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import altair as alt
import pandas as pd
import streamlit as st

from core.meteo import (
    build_meteo_profile_for_race_day,
    _compute_vlt,  # calcolo VLT del motore meteo
)


def _ctx_to_defaults(ctx: Dict[str, Any]) -> Dict[str, Any]:
    default_lat = float(ctx.get("lat", 45.833333))
    default_lon = float(ctx.get("lon", 7.733333))

    ref_dt = ctx.get("race_datetime", datetime.now())
    if isinstance(ref_dt, str):
        try:
            ref_dt = datetime.fromisoformat(ref_dt)
        except Exception:
            ref_dt = datetime.now()

    provider_default = ctx.get("provider", "auto")

    return {
        "lat": default_lat,
        "lon": default_lon,
        "race_dt": ref_dt,
        "provider": provider_default,
    }


def render_meteo_pro_dashboard(
    T: Dict[str, Any],
    ctx: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Renderizza la dashboard Meteo PRO dentro una pagina o tab esistente.

    - Non chiama st.set_page_config
    - Non imposta il titolo globale della pagina
    """

    st.markdown("### 🌡️ Meteo PRO — Ultra Weather Engine")
    st.caption("Analisi avanzata Meteoblue + Open-Meteo · Modello neve fisico v3")

    if ctx is None:
        ctx = st.session_state.get("meteo_pro_ctx", {}) or {}

    defaults = _ctx_to_defaults(ctx)

    # -------------------------------------------------------------
    # INPUT UTENTE
    # -------------------------------------------------------------
    colA, colB = st.columns(2)

    with colA:
        lat = st.number_input("Latitudine", value=defaults["lat"], format="%.6f")
        lon = st.number_input("Longitudine", value=defaults["lon"], format="%.6f")

    provider_options = ["auto", "meteoblue", "open-meteo"]
    provider_idx = provider_options.index(
        defaults["provider"] if defaults["provider"] in provider_options else "auto"
    )

    with colB:
        race_dt = st.datetime_input(
            "Data/Ora di riferimento", value=defaults["race_dt"]
        )
        provider = st.selectbox(
            "Provider meteo principale",
            provider_options,
            index=provider_idx,
        )

    st.divider()
    st.subheader("📡 Fetch meteo & profilo neve")

    profile = build_meteo_profile_for_race_day(
        {
            "lat": lat,
            "lon": lon,
            "race_datetime": race_dt,
            "provider": provider,
        }
    )

    if profile is None:
        st.error("Impossibile ottenere i dati meteo per questo giorno/località.")
        return

    # -------------------------------------------------------------
    # COSTRUZIONE DATAFRAME UNIFORME
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

    df["hour"] = df["time"].dt.strftime("%H:%M")

    # Calcolo VLT consigliata per ogni ora tramite lo stesso modello del core
    vlt_vals = []
    vlt_labels = []
    for _, row in df.iterrows():
        vlt, label = _compute_vlt(
            shade=row["shade"],
            cloud=row["cloudcover"],
            snowfall=row["snowfall"],
        )
        vlt_vals.append(vlt)
        vlt_labels.append(label)

    df["vlt_pct"] = vlt_vals
    df["vlt_label"] = vlt_labels

    # -------------------------------------------------------------
    # CARDS: CONFIDENCE + TREND
    # -------------------------------------------------------------
    st.divider()
    st.subheader("🧠 Analisi intelligente")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            "Confidence Meteo",
            f"{int(profile.confidence * 100)}%",
            help="Affidabilità stimata dei dati meteo (provider + variabilità + spike).",
        )

    with c2:
        trend_temp = profile.trend.get("temp_air", 0.0)
        arrow_t = "⬆️" if trend_temp > 0 else "⬇️" if trend_temp < 0 else "➡️"
        st.metric(
            "Trend Temperatura Aria",
            f"{trend_temp:+.2f} °C/h {arrow_t}",
        )

    with c3:
        trend_wind = profile.trend.get("wind", 0.0)
        arrow_w = "⬆️" if trend_wind > 0 else "⬇️" if trend_wind < 0 else "➡️"
        st.metric(
            "Trend Vento",
            f"{trend_wind:+.2f} km/h/h {arrow_w}",
        )

    # -------------------------------------------------------------
    # GRAFICO 1 — TEMPERATURA ARIA + NEVE
    # -------------------------------------------------------------
    st.divider()
    st.subheader("🌡️ Temperatura — Aria vs Neve (smoothed)")

    temp_chart = (
        alt.Chart(df)
        .transform_fold(
            ["temp_air", "snow_temp"],
            as_=["variable", "value"],
        )
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("time:T", title="Orario"),
            y=alt.Y("value:Q", title="Temperatura (°C)"),
            color=alt.Color("variable:N", title="Serie"),
            tooltip=[
                alt.Tooltip("time:T", title="Ora"),
                alt.Tooltip("variable:N", title="Tipo"),
                alt.Tooltip("value:Q", title="Temperatura (°C)"),
            ],
        )
        .properties(height=320)
    )

    st.altair_chart(temp_chart, use_container_width=True)

    # -------------------------------------------------------------
    # GRAFICO 2 — VENTO
    # -------------------------------------------------------------
    st.subheader("💨 Vento (km/h)")

    wind_chart = (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x="time:T",
            y=alt.Y("windspeed:Q", title="Vento (km/h)"),
            tooltip=["time:T", "windspeed:Q"],
        )
        .properties(height=220)
    )

    st.altair_chart(wind_chart, use_container_width=True)

    # -------------------------------------------------------------
    # GRAFICO 3 — UMIDITÀ + CLOUDCOVER
    # -------------------------------------------------------------
    st.subheader("💧 Umidità Relativa & ☁️ Copertura Nuvolosa")

    humid_chart = (
        alt.Chart(df)
        .mark_area(opacity=0.4)
        .encode(
            x="time:T",
            y=alt.Y("rh:Q", title="Umidità (%)"),
            tooltip=["time:T", "rh:Q"],
        )
    )

    cloud_chart = (
        alt.Chart(df)
        .mark_area(opacity=0.25)
        .encode(
            x="time:T",
            y=alt.Y("cloudcover:Q", title="Copertura Nuvolosa (%)"),
            tooltip=["time:T", "cloudcover:Q"],
        )
    )

    st.altair_chart(humid_chart + cloud_chart, use_container_width=True)

    # -------------------------------------------------------------
    # GRAFICO 4 — INDICI AVANZATI
    # -------------------------------------------------------------
    st.subheader("🏂 Indici avanzati — Shade · Moisture · Glide")

    adv_chart = (
        alt.Chart(df)
        .transform_fold(
            ["shade", "moisture", "glide"],
            as_=["variable", "value"],
        )
        .mark_line(point=True)
        .encode(
            x="time:T",
            y=alt.Y("value:Q", title="Indice (0–1)"),
            color="variable:N",
            tooltip=["time:T", "variable:N", "value:Q"],
        )
        .properties(height=320)
    )

    st.altair_chart(adv_chart, use_container_width=True)

    # -------------------------------------------------------------
    # GRAFICO 5 — VLT CONSIGLIATA
    # -------------------------------------------------------------
    st.subheader("🕶️ VLT consigliata (lente) per ogni ora")

    vlt_chart = (
        alt.Chart(df)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x="time:T",
            y=alt.Y("vlt_pct:Q", title="VLT (%)"),
            tooltip=[
                "time:T",
                "vlt_pct:Q",
                "vlt_label:N",
                "shade:Q",
                "cloudcover:Q",
                "snowfall:Q",
            ],
        )
        .properties(height=260)
    )

    st.altair_chart(vlt_chart, use_container_width=True)

    # -------------------------------------------------------------
    # CONFRONTO PROVIDER
    # -------------------------------------------------------------
    st.divider()
    st.subheader("🔁 Confronto provider Meteoblue vs Open-Meteo")

    if st.checkbox("Mostra confronto provider", value=False):
        prof_mb = build_meteo_profile_for_race_day(
            {
                "lat": lat,
                "lon": lon,
                "race_datetime": race_dt,
                "provider": "meteoblue",
            }
        )
        prof_om = build_meteo_profile_for_race_day(
            {
                "lat": lat,
                "lon": lon,
                "race_datetime": race_dt,
                "provider": "open-meteo",
            }
        )

        if prof_mb is None or prof_om is None:
            st.warning(
                "Non è stato possibile caricare entrambi i provider per il confronto."
            )
        else:
            df_mb = pd.DataFrame(
                {
                    "time": prof_mb.times,
                    "temp_air": prof_mb.temp_air,
                    "snow_temp": prof_mb.snow_temp,
                    "provider": "Meteoblue",
                }
            )
            df_om = pd.DataFrame(
                {
                    "time": prof_om.times,
                    "temp_air": prof_om.temp_air,
                    "snow_temp": prof_om.snow_temp,
                    "provider": "Open-Meteo",
                }
            )

            df_cmp = pd.concat([df_mb, df_om], ignore_index=True)

            cmp_chart = (
                alt.Chart(df_cmp)
                .transform_fold(
                    ["temp_air", "snow_temp"],
                    as_=["variable", "value"],
                )
                .mark_line()
                .encode(
                    x="time:T",
                    y=alt.Y("value:Q", title="Temperatura (°C)"),
                    color="provider:N",
                    strokeDash="variable:N",
                    tooltip=["time:T", "provider:N", "variable:N", "value:Q"],
                )
                .properties(height=320)
            )

            st.altair_chart(cmp_chart, use_container_width=True)

    # -------------------------------------------------------------
    # DOWNLOAD
    # -------------------------------------------------------------
    st.divider()
    st.subheader("📥 Download dati meteo elaborati")

    st.download_button(
        label="Scarica CSV Meteo PRO",
        data=df.to_csv(index=False),
        file_name="meteo_pro.csv",
        mime="text/csv",
    )
