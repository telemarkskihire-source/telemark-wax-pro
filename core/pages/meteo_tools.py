# core/pages/meteo_tools.py
# Modulo meteo dedicato per Telemark · Pro Wax & Tune
#
# Contiene:
#   - Profilo meteo completo (giornata intera)
#   - Supporto a tuning dinamico (build input)
#   - Pre-processing dataframe per wax module
#   - Classificazione neve
#   - Helper finestre orarie

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, date as Date, time as dtime
from typing import Dict, Any, Optional, List

import pandas as pd

from core import meteo as meteo_mod
from core.wax_logic import classify_snow


# -----------------------------------------------------------
# 1) Wrapper per costruire profilo meteo (giornata intera)
# -----------------------------------------------------------
def build_full_day_profile(ctx: Dict[str, Any]):
    """
    Usa la funzione principale già esistente:
        meteo_mod.build_meteo_profile_for_race_day(ctx)
    Ritorna direttamente il profilo o None.
    """
    try:
        return meteo_mod.build_meteo_profile_for_race_day(ctx)
    except Exception:
        return None


# -----------------------------------------------------------
# 2) Dataframe completo per grafici Altair
# -----------------------------------------------------------
def profile_to_dataframe(profile) -> pd.DataFrame:
    """
    Converte il profilo giorno intero in DataFrame completo
    per grafici e analisi.
    """
    return pd.DataFrame(
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


# -----------------------------------------------------------
# 3) Pre-processing per modulo WAX (wax_logic)
# -----------------------------------------------------------
def make_wax_dataframe(df_full: pd.DataFrame) -> pd.DataFrame:
    """
    Ritorna il dataframe pronto per wax_logic.render_wax:
    - T_surf
    - RH
    - wind
    - liq_water_pct
    - cloud
    - ptyp (snow/mixed/rain)
    """
    df = df_full.copy().reset_index(drop=True)

    df["time_local"] = df["time"]
    df["T_surf"] = df["snow_temp"]
    df["RH"] = df["rh"]
    df["wind"] = df["windspeed"]
    df["cloud"] = df["cloudcover"] / 100.0

    # acqua liquida stimata (0–?)
    if "snow_moisture_index" in df.columns:
        df["liq_water_pct"] = df["snow_moisture_index"] * 5.0
    else:
        df["liq_water_pct"] = 0.0

    # tipo precipitazione
    def _ptyp(row):
        pr = float(row.get("precipitation", 0.0))
        sf = float(row.get("snowfall", 0.0))
        if sf > 0.1 and pr - sf > 0.1:
            return "mixed"
        if sf > 0.1:
            return "snow"
        if pr > 0.1:
            return "rain"
        return None

    df["ptyp"] = df.apply(_ptyp, axis=1)
    return df[
        ["time_local", "T_surf", "RH", "wind", "liq_water_pct", "cloud", "ptyp"]
    ]


# -----------------------------------------------------------
# 4) Neve al momento di riferimento
# -----------------------------------------------------------
def get_reference_conditions(wax_df: pd.DataFrame, target_ts: datetime):
    """
    Trova la riga più vicina al timestamp indicato.
    Ritorna:
        (snow_label, row)
    """
    idx = (wax_df["time_local"] - target_ts).abs().idxmin()
    row = wax_df.loc[idx]
    snow_label = classify_snow(row)
    return snow_label, row


# -----------------------------------------------------------
# 5) Costruzione tuning dinamico
# -----------------------------------------------------------
def build_dynamic_tuning(
    profile,
    ctx: Dict[str, Any],
    discipline,
    skier_level,
    injected: bool,
):
    """
    Wrapper pulito attorno a meteo_mod.build_dynamic_tuning_for_race.
    """
    try:
        return meteo_mod.build_dynamic_tuning_for_race(
            profile=profile,
            ctx=ctx,
            discipline=discipline,
            skier_level=skier_level,
            injected=injected,
        )
    except Exception:
        return None


# -----------------------------------------------------------
# 6) Mini dataclass “giornata meteo”
# -----------------------------------------------------------
@dataclass
class DayMeteoPackage:
    """
    Package completo per la pagina:
        - df_full: dataframe completo
        - df_wax: dataframe per scioline
        - snow_label: neve al momento scelto
        - row_ref: riga meteo ref-time
    """
    df_full: pd.DataFrame
    df_wax: pd.DataFrame
    snow_label: str
    row_ref: Any


def build_day_package(profile, reference_ts: datetime) -> DayMeteoPackage:
    df_full = profile_to_dataframe(profile)
    df_wax = make_wax_dataframe(df_full)
    snow_label, row_ref = get_reference_conditions(df_wax, reference_ts)
    return DayMeteoPackage(
        df_full=df_full,
        df_wax=df_wax,
        snow_label=snow_label,
        row_ref=row_ref,
    )


# -----------------------------------------------------------
# 7) Tag icone meteo
# -----------------------------------------------------------
def make_weather_icons(df_full: pd.DataFrame) -> List[str]:
    """
    Per ogni riga crea icona meteo:
    - nevicata
    - pioggia
    - sole
    - parzialmente nuvoloso
    """
    icons = []
    for _, row in df_full.iterrows():
        cc = float(row["cloudcover"])
        pr = float(row["precipitation"])
        sf = float(row["snowfall"])

        if sf > 0.2:
            icon = "❄️"
        elif pr > 0.2:
            icon = "🌧️"
        else:
            if cc < 20:
                icon = "☀️"
            elif cc < 60:
                icon = "🌤️"
            else:
                icon = "☁️"
        icons.append(icon)
    return icons
