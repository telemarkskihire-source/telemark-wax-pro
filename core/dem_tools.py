# core/dem_tools.py
# DEM locale tramite Open-Meteo:
# - pendenza (° e %)
# - esposizione (bussola + gradi)
# - stima ombreggiatura
#   · all'ora attuale
#   · all'ora di gara (se ctx["race_datetime"] presente)
# - altitudine con override manuale per ogni punto selezionato

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, Any

import requests
import numpy as np
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/2.0"}


def dem_patch(lat: float, lon: float, spacing_m: int = 30, size: int = 3):
    half = size // 2
    dlat = spacing_m / 111320.0
    dlon = spacing_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))
    lats, lons = [], []
    for j in range(size):
        for i in range(size):
            lats.append(lat + (j - half) * dlat)
            lons.append(lon + (i - half) * dlon)

    params = {
        "latitude": ",".join(f"{x:.6f}" for x in lats),
        "longitude": ",".join(f"{x:.6f}" for x in lons),
    }
    r = requests.get(
        "https://api.open-meteo.com/v1/elevation",
        params=params,
        headers=UA,
        timeout=10,
    )
    r.raise_for_status()
    js = r.json()
    elevs = js.get("elevation")
    if not elevs or len(elevs) != size * size:
        return None
    Z = np.array(elevs, dtype=float).reshape(size, size)
    return {"Z": Z, "spacing_m": spacing_m}


def slope_aspect_from_dem(Z, spacing_m):
    dzdx = (
        (Z[0, 2] + 2 * Z[1, 2] + Z[2, 2])
        - (Z[0, 0] + 2 * Z[1, 0] + Z[2, 0])
    ) / (8.0 * spacing_m)
    dzdy = (
        (Z[2, 0] + 2 * Z[2, 1] + Z[2, 2])
        - (Z[0, 0] + 2 * Z[0, 1] + Z[0, 2])
    ) / (8.0 * spacing_m)

    slope_rad = math.atan(math.hypot(dzdx, dzdy))
    slope_deg = math.degrees(slope_rad)
    slope_pct = math.tan(slope_rad) * 100.0

    aspect_rad = math.atan2(dzdx, dzdy)  # convenzione N=0
    aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0
    return float(slope_deg), float(slope_pct), float(aspect_deg)


def aspect_to_compass(deg: float):
    dirs = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    idx = int((deg + 11.25) // 22.5) % 16
    return dirs[idx]


def _base_shade_from_aspect(aspect_deg: float) -> str:
    """
    Classificazione generica (senza orario), solo da esposizione:
    stessa logica che avevamo prima.
    """
    d = aspect_deg % 360
    if (315 <= d <= 360) or (0 <= d <= 45):
        return "molto ombreggiata"
    if 45 < d < 135 or 225 < d < 315:
        return "parzialmente in ombra"
    return "molto soleggiata"


def shade_with_time(aspect_deg: float, hour_local: float) -> str:
    """
    Stima qualitativa di ombreggiatura che tiene conto grossolanamente dell'orario.
    Idea:
      - mattina (<10): pendii EST/SE più soleggiati, OVEST/NO più in ombra
      - mezzogiorno (10–14): usa classificazione base
      - pomeriggio (>14): pendii OVEST/SO più soleggiati, EST/NE più in ombra
    """
    d = aspect_deg % 360
    base = _base_shade_from_aspect(d)

    # zona oraria approssimata in blocchi
    if hour_local < 10.0:  # mattina
        if 45 <= d <= 150:  # NE–SE rivolti verso il sole del mattino
            return "molto soleggiata"
        if 210 <= d <= 330:  # SO–NO
            return "molto ombreggiata"
        return "parzialmente in ombra" if base != "molto soleggiata" else base

    if 10.0 <= hour_local <= 14.0:
        return base  # metà giornata: esposizione quasi "pura"

    # pomeriggio / sera
    if 210 <= d <= 300:  # S–SO–O
        return "molto soleggiata"
    if 30 <= d <= 150:  # NE–E–SE
        return "molto ombreggiata"
    return "parzialmente in ombra" if base != "molto soleggiata" else base


def render_dem(T: Dict[str, str], ctx: Dict[str, Any]):
    lat = float(ctx.get("lat", 45.83333))
    lon = float(ctx.get("lon", 7.73333))

    hdr = T.get("dem_hdr", "Esposizione & pendenza (DEM locale)")
    err_msg = T.get("dem_err", "DEM non disponibile ora. Riprova tra poco.")

    with st.expander(hdr, expanded=False):
        try:
            dem = dem_patch(lat, lon)
        except Exception:
            dem = None

        if not dem:
            st.warning(err_msg)
            return

        Z = dem["Z"]
        spacing_m = dem["spacing_m"]

        sdeg, spct, adeg = slope_aspect_from_dem(Z, spacing_m)
        compass = aspect_to_compass(adeg)

        # altitudine DEM al centro patch
        center_alt = float(Z[Z.shape[0] // 2, Z.shape[1] // 2])

        # chiave per override legata a lat/lon -> cambia quando cambi pista/punto
        alt_key = f"altitude_override_m_{round(lat,5)}_{round(lon,5)}"
        default_alt = float(st.session_state.get(alt_key, center_alt))

        alt = st.number_input(
            T.get("altitude_m", "Altitudine punto selezionato (m)"),
            min_value=-100.0,
            max_value=6000.0,
            value=float(round(default_alt, 1)),
            step=10.0,
        )
        st.session_state[alt_key] = alt
        ctx["altitude_m"] = alt

        c1, c2, c3 = st.columns(3)
        c1.metric(T.get("slope_deg", "Pendenza (°)"), f"{sdeg:.1f}°")
        c2.metric(T.get("slope_pct", "Pendenza (%)"), f"{int(round(spct))}%")
        c3.metric(
            T.get("aspect_dir", "Esposizione (bussola)"),
            f"{compass} ({adeg:.0f}°)",
        )

        # ---- Ombreggiatura: adesso + ora gara (se presente) ----
        now = datetime.now()
        now_hour = now.hour + now.minute / 60.0
        shade_now = shade_with_time(adeg, now_hour)

        race_dt = ctx.get("race_datetime")
        if isinstance(race_dt, datetime):
            race_hour = race_dt.hour + race_dt.minute / 60.0
            shade_race = shade_with_time(adeg, race_hour)

            st.caption(
                f"Ora attuale ~{now_hour:.1f}h → stima ombreggiatura: {shade_now}."
            )
            st.caption(
                f"Ora gara {race_dt.strftime('%Y-%m-%d · %H:%M')} → "
                f"stima ombreggiatura: {shade_race}."
            )
        else:
            st.caption(
                f"Stima ombreggiatura ora (~{now_hour:.1f}h): {shade_now}."
            )

        st.caption(f"Altitudine DEM di riferimento (centro patch): {center_alt:.0f} m")


# alias per compatibilità
render_slope_shade_panel = render_dem
dem_panel = render_dem
show_dem = render_dem
app = render = render_dem
