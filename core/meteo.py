# core/meteo.py
# Meteo oraria + profilo neve / visibilità per Telemark · Pro Wax & Tune

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import List, Optional

import numpy as np
import requests
import streamlit as st

from core.dem_tools import dem_patch, slope_aspect_from_dem, aspect_to_compass
from core.race_tuning import (
    TuningParamsInput,
    Discipline,
    SkierLevel,
    SnowType,
    get_tuning_recommendation,
)

UA = {"User-Agent": "telemark-wax-pro/2.0"}


@dataclass
class MeteoProfile:
    times: List[datetime]
    air_temp: np.ndarray
    snow_temp: np.ndarray
    cloud_cover: np.ndarray
    precip: np.ndarray
    wind_speed: np.ndarray
    rel_humidity: np.ndarray
    uv_index: np.ndarray


@dataclass
class DynamicTuningResult:
    snow_temp_c: float
    air_temp_c: float
    slope_deg: float
    aspect_deg: float
    aspect_txt: str
    base_bevel_deg: float
    side_bevel_deg: float
    structure_pattern: str
    wax_group: str
    risk_level: str      # lo chiamiamo "Profilo" nella UI
    notes: str
    visibility_index: float
    visibility_txt: str


# ---------------------------------------------------------------------------
# Fetch meteo oraria da Open-Meteo
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30 * 60, show_spinner=False)
def _fetch_hourly_meteo(
    lat: float,
    lon: float,
    start: date,
    end: date,
) -> Optional[dict]:
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "cloud_cover",
                    "precipitation",
                    "wind_speed_10m",
                    "uv_index",
                ]
            ),
            "timezone": "auto",
        }
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            headers=UA,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _estimate_snow_temp_series(air_degC: np.ndarray) -> np.ndarray:
    if air_degC.size == 0:
        return air_degC

    snow = np.minimum(air_degC - 0.5, 0.0)

    kernel = np.array([0.25, 0.5, 0.25])
    pad = np.pad(snow, (1, 1), mode="edge")
    smooth = np.convolve(pad, kernel, mode="valid")
    return smooth.astype(float)


# ---------------------------------------------------------------------------
# Costruzione profilo meteo per la giornata gara
# ---------------------------------------------------------------------------

def build_meteo_profile_for_race_day(ctx: dict) -> Optional[MeteoProfile]:
    if "lat" not in ctx or "lon" not in ctx:
        return None

    lat = float(ctx["lat"])
    lon = float(ctx["lon"])
    race_dt: datetime = ctx.get("race_datetime") or datetime.utcnow()
    race_day = race_dt.date()
    start = race_day - timedelta(days=1)
    end = race_day

    js = _fetch_hourly_meteo(lat, lon, start, end)
    if not js or "hourly" not in js:
        return None

    h = js["hourly"]
    times_raw = h.get("time") or []
    if not times_raw:
        return None

    times = [datetime.fromisoformat(t) for t in times_raw]

    def _arr(key: str) -> np.ndarray:
        return np.array(h.get(key) or [], dtype=float)

    air = _arr("temperature_2m")
    rh = _arr("relative_humidity_2m")
    cloud = _arr("cloud_cover")
    precip = _arr("precipitation")
    wind = _arr("wind_speed_10m")
    uv = _arr("uv_index")

    n = len(times)
    for arr in (air, rh, cloud, precip, wind, uv):
        if arr.size != n:
            return None

    snow = _estimate_snow_temp_series(air)

    return MeteoProfile(
        times=times,
        air_temp=air,
        snow_temp=snow,
        cloud_cover=cloud,
        precip=precip,
        wind_speed=wind,
        rel_humidity=rh,
        uv_index=uv,
    )


# ---------------------------------------------------------------------------
# Dinamica gara: DEM + meteo + tuning
# ---------------------------------------------------------------------------

def _snow_type_from_conditions(
    snow_temp_c: float,
    rh_pct: float,
    precip_mm: float,
) -> SnowType:
    if snow_temp_c <= -8.0:
        return SnowType.DRY
    if precip_mm > 0.5 and snow_temp_c > -3.0:
        return SnowType.WET
    if snow_temp_c > -2.0 and rh_pct > 80.0:
        return SnowType.WET
    if snow_temp_c <= -2.0:
        return SnowType.PACKED
    return SnowType.PACKED


def _visibility_index_from_meteo(
    uv: float,
    cloud_cover: float,
    precip_mm: float,
    aspect_deg: float,
) -> float:
    uv_norm = max(0.0, min(1.0, uv / 8.0))
    clouds_norm = 1.0 - max(0.0, min(1.0, cloud_cover / 100.0))
    precip_norm = max(0.0, 1.0 - min(precip_mm, 3.0) / 3.0)

    base = 0.5 * uv_norm + 0.3 * clouds_norm + 0.2 * precip_norm

    # penalizza versanti Nord
    if 315 <= aspect_deg or aspect_deg < 45:
        base *= 0.8
    elif 45 <= aspect_deg < 135:
        base *= 0.95
    elif 135 <= aspect_deg < 225:
        base *= 1.0
    else:
        base *= 0.9

    base = max(0.0, min(1.0, base))
    return float(round(base * 100))


def _visibility_text(idx: float, lang: str) -> str:
    if idx >= 70:
        return "Alta" if lang == "IT" else "High"
    if idx >= 40:
        return "Media" if lang == "IT" else "Medium"
    return "Bassa" if lang == "IT" else "Low"


def build_dynamic_tuning_for_race(
    profile: MeteoProfile,
    ctx: dict,
    discipline: Discipline,
    skier_level: SkierLevel,
    injected: bool,
) -> Optional[DynamicTuningResult]:
    lat = float(ctx.get("lat", 0.0))
    lon = float(ctx.get("lon", 0.0))
    race_dt: datetime = ctx.get("race_datetime") or datetime.utcnow()
    lang = ctx.get("lang", "IT")

    dem = dem_patch(lat, lon)
    if not dem:
        slope_deg = 0.0
        aspect_deg = 180.0
        aspect_txt = "S"
    else:
        slope_deg, _, aspect_deg = slope_aspect_from_dem(
            dem["Z"], dem["spacing_m"]
        )
        aspect_txt = aspect_to_compass(aspect_deg)

    times = profile.times
    if not times:
        return None

    idx_closest = min(
        range(len(times)),
        key=lambda i: abs((times[i] - race_dt).total_seconds()),
    )

    air = float(profile.air_temp[idx_closest])
    snow = float(profile.snow_temp[idx_closest])
    rh = float(profile.rel_humidity[idx_closest])
    precip = float(profile.precip[idx_closest])
    uv = float(profile.uv_index[idx_closest])
    clouds = float(profile.cloud_cover[idx_closest])

    snow_type = _snow_type_from_conditions(snow, rh, precip)

    params_input = TuningParamsInput(
        discipline=discipline,
        snow_temp_c=snow,
        air_temp_c=air,
        snow_type=snow_type,
        injected=injected,
        skier_level=skier_level,
    )
    rec = get_tuning_recommendation(params_input)

    vis_idx = _visibility_index_from_meteo(uv, clouds, precip, aspect_deg)
    vis_txt = _visibility_text(vis_idx, lang)

    return DynamicTuningResult(
        snow_temp_c=snow,
        air_temp_c=air,
        slope_deg=slope_deg,
        aspect_deg=aspect_deg,
        aspect_txt=aspect_txt,
        base_bevel_deg=rec.base_bevel_deg,
        side_bevel_deg=rec.side_bevel_deg,
        structure_pattern=rec.structure_pattern,
        wax_group=rec.wax_group,
        risk_level=rec.risk_level,
        notes=rec.notes,
        visibility_index=vis_idx,
        visibility_txt=vis_txt,
    )
