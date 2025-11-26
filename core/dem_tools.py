# core/dem_tools.py
# DEM locale tramite Open-Meteo:
# - pendenza (° e %)
# - esposizione (bussola + gradi)
# - stima ombreggiatura:
#     · ora attuale
#     · ora gara (se ctx["race_datetime"] presente)
#   con correzione qualitativa in base alla nuvolosità
# - altitudine con override manuale per ogni punto selezionato
# - espone in ctx anche un mini pacchetto meteo per ora attuale / ora gara

from __future__ import annotations

import math
from datetime import datetime
from typing import Dict, Any, Optional

import requests
import numpy as np
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/2.1"}


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

    aspect_rad = math.atan2(dzdx, dzdy)  # N=0
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
    d = aspect_deg % 360
    if (315 <= d <= 360) or (0 <= d <= 45):
        return "molto ombreggiata"
    if 45 < d < 135 or 225 < d < 315:
        return "parzialmente in ombra"
    return "molto soleggiata"


def shade_with_time(aspect_deg: float, hour_local: float) -> str:
    d = aspect_deg % 360
    base = _base_shade_from_aspect(d)

    if hour_local < 10.0:  # mattina
        if 45 <= d <= 150:  # NE–SE
            return "molto soleggiata"
        if 210 <= d <= 330:  # SO–NO
            return "molto ombreggiata"
        return "parzialmente in ombra" if base != "molto soleggiata" else base

    if 10.0 <= hour_local <= 14.0:
        return base

    # pomeriggio
    if 210 <= d <= 300:  # S–SO–O
        return "molto soleggiata"
    if 30 <= d <= 150:  # NE–E–SE
        return "molto ombreggiata"
    return "parzialmente in ombra" if base != "molto soleggiata" else base


@st.cache_data(ttl=900, show_spinner=False)
def _hourly_weather_for_date(lat: float, lon: float, date_str: str) -> Optional[Dict[str, Any]]:
    """
    Recupera meteo oraria da Open-Meteo per una singola data:
    - temperatura 2m
    - umidità relativa
    - copertura nuvolosa
    - vento
    - precipitazione / neve
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relativehumidity_2m,cloudcover,windspeed_10m,precipitation,snowfall",
        "start_date": date_str,
        "end_date": date_str,
        "timezone": "auto",
    }
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            headers=UA,
            timeout=10,
        )
        r.raise_for_status()
        js = r.json() or {}
        return js.get("hourly") or None
    except Exception:
        return None


def _interp_hourly(weather: Dict[str, Any], target_hour: int) -> Dict[str, float]:
    """
    Estrae il valore più vicino all'ora target (0-23).
    """
    times = weather.get("time") or []
    if not times:
        return {}

    idx_best = None
    best_diff = 999
    for idx, t in enumerate(times):
        # formato "YYYY-MM-DDTHH:MM"
        try:
            hh = int(t[11:13])
        except Exception:
            continue
        diff = abs(hh - target_hour)
        if diff < best_diff:
            best_diff = diff
            idx_best = idx

    if idx_best is None:
        return {}

    def _get(name: str):
        arr = weather.get(name) or []
        if idx_best < len(arr):
            try:
                return float(arr[idx_best])
            except Exception:
                return None
        return None

    return {
        "temp_air": _get("temperature_2m"),
        "rh": _get("relativehumidity_2m"),
        "cloudcover": _get("cloudcover"),
        "windspeed": _get("windspeed_10m"),
        "precip": _get("precipitation"),
        "snowfall": _get("snowfall"),
    }


def _shade_with_meteo(aspect_deg: float, hour_local: float, cloudcover: Optional[float]) -> str:
    """
    Integra nuvolosità: se copertura molto alta, anche un pendio "molto soleggiata"
    diventa luce diffusa / meno impattante sulla neve.
    """
    base = shade_with_time(aspect_deg, hour_local)
    if cloudcover is None:
        return base

    if cloudcover >= 85:
        # cielo coperto, luce piatta
        if "soleggiata" in base:
            return "luce diffusa (cielo coperto), ombreggiatura poco rilevante"
        if "ombreggiata" in base:
            return "ombreggiata ma con cielo coperto (contrasto ridotto)"
        return "luce diffusa (cielo coperto)"
    if 50 <= cloudcover < 85:
        # parzialmente nuvoloso
        if "molto soleggiata" in base:
            return "parzialmente soleggiata (nuvolosità variabile)"
        return base
    # cielo abbastanza sereno
    return base


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

        center_alt = float(Z[Z.shape[0] // 2, Z.shape[1] // 2])

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

        # ---------- METEO + OMBREGGIATURA ----------
        now = datetime.now()
        now_hour = now.hour + now.minute / 60.0
        race_dt = ctx.get("race_datetime")
        has_race = isinstance(race_dt, datetime)

        # meteo ora attuale
        weather_now = _hourly_weather_for_date(lat, lon, now.date().isoformat())
        sample_now = _interp_hourly(weather_now, now.hour) if weather_now else {}

        cloud_now = sample_now.get("cloudcover")
        shade_now = _shade_with_meteo(adeg, now_hour, cloud_now)

        ctx["meteo_now"] = sample_now

        if has_race:
            weather_race = _hourly_weather_for_date(lat, lon, race_dt.date().isoformat())
            sample_race = _interp_hourly(weather_race, race_dt.hour) if weather_race else {}
            cloud_race = sample_race.get("cloudcover")
            race_hour = race_dt.hour + race_dt.minute / 60.0
            shade_race = _shade_with_meteo(adeg, race_hour, cloud_race)
            ctx["meteo_race"] = sample_race

            st.caption(
                f"Ora attuale ~{now_hour:.1f}h → ombreggiatura stimata: {shade_now} "
                + (f"(nuvolosità ~{cloud_now:.0f}%)." if cloud_now is not None else ".")
            )
            st.caption(
                f"Ora gara {race_dt.strftime('%Y-%m-%d · %H:%M')} → ombreggiatura stimata: {shade_race} "
                + (f"(nuvolosità ~{cloud_race:.0f}%)." if cloud_race is not None else ".")
            )
        else:
            st.caption(
                f"Stima ombreggiatura ora (~{now_hour:.1f}h): {shade_now} "
                + (f"(nuvolosità ~{cloud_now:.0f}%)." if cloud_now is not None else ".")
            )

        st.caption(f"Altitudine DEM di riferimento (centro patch): {center_alt:.0f} m")


# alias
render_slope_shade_panel = render_dem
dem_panel = render_dem
show_dem = render_dem
app = render = render_dem
