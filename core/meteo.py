# core/meteo.py
# Modello meteo & profilo neve per Telemark · Pro Wax & Tune
#
# - Fetch da Open-Meteo (hourly) per giorno/località
#   con models=gfs_seamless (fonte NOAA GFS)
# - Costruzione profilo:
#     · temperatura aria
#     · temperatura neve (nuovo modello calibrato)
#     · umidità, vento, copertura nuvole
#     · indici: shade_index, snow_moisture_index, glide_index
# - Tuning dinamico: costruisce TuningParamsInput per la gara
# - Output:
#     · MeteoProfile
#     · DynamicTuningResult (con vlt_pct e vlt_label)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date as Date
from typing import List, Optional, Dict, Any

import requests
import pandas as pd

from core.race_tuning import (
    SnowType,
    TuningParamsInput,
    SkierLevel,
    Discipline,
)

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ------------------------------------------------------------------
# Nuovo modello temperatura neve superficiale
# ------------------------------------------------------------------
@dataclass
class SnowTempContext:
    air_temp_c: float           # T aria a 2 m (°C)
    rel_humidity_pct: float     # UR (%)
    is_night: bool              # True = notte, False = giorno
    sky_condition: str          # "clear", "partly", "overcast"


def estimate_surface_snow_temperature(ctx: SnowTempContext) -> float:
    """
    Stima T neve (°C) dai parametri principali.
    Calibrata su Champoluc: aria -1.3 °C, UR 93%, neve ~ -2.4 °C.
    """
    ta = ctx.air_temp_c
    rh = max(0.0, min(100.0, ctx.rel_humidity_pct))

    # base_delta cresce con l'umidità
    #  - a 70% → ~0.6 °C
    #  - a 90–100% → ~1.1–1.3 °C
    base_delta = 0.6 + 0.025 * max(0.0, rh - 70.0)

    if ctx.is_night:
        base_delta += 0.2
    else:
        sc = ctx.sky_condition.lower()
        if sc in {"clear", "sunny"}:
            base_delta -= 0.2  # sole scalda la neve
        elif sc in {"partly", "partly_cloudy"}:
            base_delta -= 0.1  # un po' di sole = neve meno fredda

    # limiti fisicamente sensati
    base_delta = max(0.3, min(1.5, base_delta))

    t_snow = ta - base_delta
    # clamp morbido: neve non sopra 0, non assurda tipo -50
    t_snow = max(-35.0, min(t_snow, -0.0))
    return float(t_snow)


# ------------------------------------------------------------------
# Dataclass output profilo meteo
# ------------------------------------------------------------------
@dataclass
class MeteoProfile:
    times: List[datetime]
    temp_air: List[float]
    snow_temp: List[float]
    rh: List[float]
    cloudcover: List[float]
    windspeed: List[float]
    precip: List[float]
    snowfall: List[float]
    shade_index: List[float]
    snow_moisture_index: List[float]
    glide_index: List[float]


@dataclass
class DynamicTuningResult:
    input_params: TuningParamsInput
    snow_type: SnowType
    vlt_pct: float
    vlt_label: str
    summary: str


# ------------------------------------------------------------------
# Fetch da Open-Meteo (con models=gfs_seamless → NOAA GFS)
# ------------------------------------------------------------------
def _fetch_hourly_meteo(
    lat: float,
    lon: float,
    target_day: Date,
) -> Optional[pd.DataFrame]:
    """
    Scarica dati orari da Open-Meteo per il giorno target_day su (lat, lon).
    Usa models=gfs_seamless (fonte NOAA GFS).

    Ritorna DataFrame con colonne:
      time, temp_air, rh, cloudcover, windspeed, precip, snowfall, sw_rad
    oppure None in caso di errore.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation",
                "snowfall",
                "cloudcover",
                "wind_speed_10m",
                "shortwave_radiation",
            ]
        ),
        "timezone": "auto",
        "start_date": target_day.isoformat(),
        "end_date": target_day.isoformat(),
        # qui abilitiamo il modello NOAA GFS "seamless"
        "models": "gfs_seamless",
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
    except Exception:
        return None

    hourly = js.get("hourly")
    if not hourly:
        return None

    times = hourly.get("time") or []
    if not times:
        return None

    df = pd.DataFrame(
        {
            "time": pd.to_datetime(times),
            "temp_air": hourly.get("temperature_2m", []),
            "rh": hourly.get("relative_humidity_2m", []),
            "precip": hourly.get("precipitation", []),
            "snowfall": hourly.get("snowfall", []),
            "cloudcover": hourly.get("cloudcover", []),
            "windspeed": hourly.get("wind_speed_10m", []),
            "sw_rad": hourly.get("shortwave_radiation", []),
        }
    )

    # Garantiamo i tipi float
    for col in [
        "temp_air",
        "rh",
        "precip",
        "snowfall",
        "cloudcover",
        "windspeed",
        "sw_rad",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["temp_air"])
    if df.empty:
        return None

    return df


# ------------------------------------------------------------------
# Utility fisiche / indici
# ------------------------------------------------------------------
def _local_time_of_day_fraction(ts: datetime) -> float:
    """
    Ritorna frazione del giorno locale (0 = mezzanotte, 0.5 = mezzogiorno).
    """
    return (ts.hour + ts.minute / 60.0) / 24.0


def _compute_shade_index(row: pd.Series) -> float:
    """
    Indice ombreggiatura / luce piatta:
      0 = pieno sole
      1 = ombra / luce piatta / cielo coperto
    Combina radiazione solare e copertura nuvolosa.
    """
    rad = float(row.get("sw_rad", 0.0) or 0.0)
    cc = float(row.get("cloudcover", 0.0) or 0.0)  # 0–100

    # 0 W/m² = notte / ombra totale
    # ~ 600–800 W/m² = sole pieno
    rad_norm = max(0.0, min(rad / 700.0, 1.0))

    shade_from_rad = 1.0 - rad_norm
    cloud_factor = cc / 100.0

    shade = 0.6 * shade_from_rad + 0.4 * cloud_factor
    return float(max(0.0, min(shade, 1.0)))


def _compute_snow_moisture_index(
    snow_temp_c: float,
    rh_pct: float,
    precip_mm: float,
    snowfall_cm: float,
) -> float:
    """
    Indice 0–1 di umidità neve.

    0   = neve molto secca / polvere fredda
    0.5 = compatta / standard
    1   = bagnata / primaverile
    """
    # base da temperatura neve
    if snow_temp_c <= -10:
        idx = 0.05
    elif snow_temp_c <= -6:
        idx = 0.15
    elif snow_temp_c <= -3:
        idx = 0.3
    elif snow_temp_c <= -1:
        idx = 0.5
    else:
        idx = 0.7

    # umidità aria
    if rh_pct > 90:
        idx += 0.1
    elif rh_pct < 50:
        idx -= 0.1

    # precipitazioni liquide -> neve più umida
    if precip_mm > 0.5 and snowfall_cm < 0.1:
        idx += 0.2

    # neve intensa ma fredda -> può restare relativamente secca
    if snowfall_cm > 2.0 and snow_temp_c < -3:
        idx -= 0.1

    return float(max(0.0, min(idx, 1.0)))


def _compute_glide_index(
    snow_temp_c: float,
    moisture_idx: float,
    shade_idx: float,
) -> float:
    """
    Indice 0–1 di scorrevolezza teorica.
    Neve troppo fredda e secca -> poca scorrevolezza
    Neve leggermente calda e un po’ umida -> massima
    Neve troppo bagnata -> cala di nuovo
    """
    # base da temperatura
    if snow_temp_c <= -12:
        base = 0.2
    elif snow_temp_c <= -6:
        base = 0.35
    elif snow_temp_c <= -2:
        base = 0.55
    elif snow_temp_c <= -0.5:
        base = 0.7
    else:
        base = 0.6

    # umidità
    if moisture_idx < 0.2:
        base -= 0.1
    elif 0.2 <= moisture_idx <= 0.6:
        base += 0.1
    else:
        base -= 0.05  # troppo bagnata

    # ombra: luce piatta / freddo tende a rendere più “appiccicoso”
    base -= 0.1 * (shade_idx - 0.5)

    return float(max(0.0, min(base, 1.0)))


def _classify_snow_type(
    snow_temp_c: float,
    moisture_idx: float,
    injected: bool,
) -> SnowType:
    """
    Mappa (T neve, umidità, injected) su uno SnowType.
    Usa nomi "classici" se esistono nella Enum, altrimenti ripiega
    sul primo elemento disponibile.
    """
    fallback = list(SnowType)[0]

    try:
        if injected and hasattr(SnowType, "ICE_INJECTED"):
            return SnowType.ICE_INJECTED  # type: ignore[attr-defined]

        if snow_temp_c <= -10 and hasattr(SnowType, "VERY_COLD_DRY"):
            return SnowType.VERY_COLD_DRY  # type: ignore[attr-defined]
        if snow_temp_c <= -6 and moisture_idx < 0.3 and hasattr(SnowType, "COLD_DRY"):
            return SnowType.COLD_DRY  # type: ignore[attr-defined]
        if -6 < snow_temp_c <= -2 and hasattr(SnowType, "COLD_MID"):
            return SnowType.COLD_MID  # type: ignore[attr-defined]
        if -2 < snow_temp_c <= -0.5 and moisture_idx <= 0.7 and hasattr(
            SnowType, "NEAR_ZERO"
        ):
            return SnowType.NEAR_ZERO  # type: ignore[attr-defined]
        if moisture_idx > 0.7 and hasattr(SnowType, "WET"):
            return SnowType.WET  # type: ignore[attr-defined]

    except Exception:
        return fallback

    return fallback


def _compute_vlt_recommendation(
    shade_idx: float,
    cloudcover_pct: float,
    snowfall_mm: float,
) -> (float, str):
    """
    Stima VLT consigliata (in %) e label descrittivo.
    Logica semplice ma robusta:
      - molto sole / poca nuvolosità -> VLT bassa (occhiale scuro)
      - nuvoloso / flat light / nevicata -> VLT alta (lente chiara)
    """
    cc = cloudcover_pct
    shade = shade_idx
    snowing = snowfall_mm > 0.2

    # base
    if snowing or shade > 0.7 or cc > 80:
        vlt = 55.0  # molto chiaro
    elif shade > 0.5 or cc > 60:
        vlt = 45.0
    elif shade > 0.3 or cc > 40:
        vlt = 35.0
    else:
        vlt = 18.0  # sole pieno

    # clamp
    vlt = max(8.0, min(vlt, 70.0))

    # label
    if vlt <= 15:
        label = "S3 / molto scuro"
    elif vlt <= 25:
        label = "S2–S3 / sole forte"
    elif vlt <= 40:
        label = "S2 / variabile"
    elif vlt <= 55:
        label = "S1–S2 / luce piatta"
    else:
        label = "S1 / low light / notte"

    return float(vlt), label


# ------------------------------------------------------------------
# Costruzione profilo giornaliero per località / gara
# ------------------------------------------------------------------
def build_meteo_profile_for_race_day(ctx: Dict[str, Any]) -> Optional[MeteoProfile]:
    """
    Costruisce un profilo meteo per l'intera giornata di gara/località.

    ctx deve contenere:
      - "lat", "lon"
      - "race_datetime": datetime (usato per il giorno)
    """
    lat = float(ctx.get("lat", 45.83333))
    lon = float(ctx.get("lon", 7.73333))

    race_dt: Optional[datetime] = ctx.get("race_datetime")
    if not isinstance(race_dt, datetime):
        # se manca, usiamo oggi (UTC) ma è una situazione di fallback
        race_dt = datetime.utcnow()
    target_day = race_dt.date()

    df = _fetch_hourly_meteo(lat, lon, target_day)
    if df is None or df.empty:
        return None

    # Calcolo degli indici e della T neve
    snow_temps: List[float] = []
    shade_idxs: List[float] = []
    moisture_idxs: List[float] = []
    glide_idxs: List[float] = []

    for _, row in df.iterrows():
        ts: datetime = row["time"]
        tod_frac = _local_time_of_day_fraction(ts)

        shade = _compute_shade_index(row)
        shade_idxs.append(shade)

        t_air = float(row["temp_air"])
        rh = float(row.get("rh", 80.0) or 80.0)
        precip = float(row.get("precip", 0.0) or 0.0)
        snowfall = float(row.get("snowfall", 0.0) or 0.0)

        # cm approx from mm for neve (non perfetto, ma sufficiente per indice)
        snowfall_cm = snowfall

        # definisco notte / giorno e cielo per il modello neve
        hour = tod_frac * 24.0
        is_night = hour < 6 or hour >= 18

        cc = float(row.get("cloudcover", 0.0) or 0.0)
        rad = float(row.get("sw_rad", 0.0) or 0.0)

        if rad > 300 and cc < 30:
            sky_condition = "clear"
        elif cc > 70:
            sky_condition = "overcast"
        else:
            sky_condition = "partly"

        snow_ctx = SnowTempContext(
            air_temp_c=t_air,
            rel_humidity_pct=rh,
            is_night=is_night,
            sky_condition=sky_condition,
        )
        t_snow = estimate_surface_snow_temperature(snow_ctx)
        snow_temps.append(t_snow)

        moisture = _compute_snow_moisture_index(
            snow_temp_c=t_snow,
            rh_pct=rh,
            precip_mm=precip,
            snowfall_cm=snowfall_cm,
        )
        moisture_idxs.append(moisture)

        glide = _compute_glide_index(
            snow_temp_c=t_snow,
            moisture_idx=moisture,
            shade_idx=shade,
        )
        glide_idxs.append(glide)

    df["snow_temp"] = snow_temps
    df["shade_index"] = shade_idxs
    df["snow_moisture_index"] = moisture_idxs
    df["glide_index"] = glide_idxs

    return MeteoProfile(
        times=list(df["time"]),
        temp_air=list(df["temp_air"]),
        snow_temp=list(df["snow_temp"]),
        rh=list(df["rh"]),
        cloudcover=list(df["cloudcover"]),
        windspeed=list(df["windspeed"]),
        precip=list(df["precip"]),
        snowfall=list(df["snowfall"]),
        shade_index=list(df["shade_index"]),
        snow_moisture_index=list(df["snow_moisture_index"]),
        glide_index=list(df["glide_index"]),
    )


# ------------------------------------------------------------------
# Tuning dinamico basato su profilo meteo
# ------------------------------------------------------------------
def build_dynamic_tuning_for_race(
    profile: MeteoProfile,
    ctx: Dict[str, Any],
    discipline: Discipline,
    skier_level: SkierLevel,
    injected: bool,
) -> Optional[DynamicTuningResult]:
    """
    Usa il profilo meteo + info gara per costruire:
      - TuningParamsInput
      - classifica SnowType
      - VLT consigliata
    """
    if profile is None or not profile.times:
        return None

    race_dt: Optional[datetime] = ctx.get("race_datetime")
    if not isinstance(race_dt, datetime):
        # fallback: mezzogiorno del primo giorno in profilo
        race_dt = profile.times[0].replace(hour=12, minute=0, second=0, microsecond=0)

    # find closest time index
    times = profile.times
    deltas = [abs((t - race_dt).total_seconds()) for t in times]
    idx = int(deltas.index(min(deltas)))

    snow_temp_c = float(profile.snow_temp[idx])
    air_temp_c = float(profile.temp_air[idx])
    rh_pct = float(profile.rh[idx])
    cloud_pct = float(profile.cloudcover[idx])
    wind_kmh = float(profile.windspeed[idx])
    shade_idx = float(profile.shade_index[idx])
    moist_idx = float(profile.snow_moisture_index[idx])
    glide_idx = float(profile.glide_index[idx])
    snowfall_mm = float(profile.snowfall[idx])
    precip_mm = float(profile.precip[idx])

    snow_type = _classify_snow_type(
        snow_temp_c=snow_temp_c,
        moisture_idx=moist_idx,
        injected=injected,
    )

    vlt_pct, vlt_label = _compute_vlt_recommendation(
        shade_idx=shade_idx,
        cloudcover_pct=cloud_pct,
        snowfall_mm=snowfall_mm,
    )

    # Costruiamo l'input per il modulo race_tuning
    params = TuningParamsInput(
        snow_temp_c=snow_temp_c,
        air_temp_c=air_temp_c,
        rh_pct=rh_pct,
        snow_type=snow_type,
        discipline=discipline,
        skier_level=skier_level,
        injected=injected,
        shade_index=shade_idx,
        moisture_index=moist_idx,
        glide_index=glide_idx,
        wind_speed_kmh=wind_kmh,
        cloudcover_pct=cloud_pct,
        precip_mm=precip_mm,
        snowfall_mm=snowfall_mm,
    )

    # Summary umano
    dt_str = race_dt.strftime("%Y-%m-%d · %H:%M")
    summary = (
        f"Tuning dinamico per {dt_str} — "
        f"neve {snow_temp_c:.1f} °C, aria {air_temp_c:.1f} °C, "
        f"UR {rh_pct:.0f}%, vento {wind_kmh:.0f} km/h, "
        f"shade {shade_idx:.2f}, moisture {moist_idx:.2f}, "
        f"glide {glide_idx:.2f}, VLT {vlt_pct:.0f}% ({vlt_label})."
    )

    return DynamicTuningResult(
        input_params=params,
        snow_type=snow_type,
        vlt_pct=vlt_pct,
        vlt_label=vlt_label,
        summary=summary,
    )
