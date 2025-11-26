# core/meteo.py
# Meteo avanzata per Telemark · Pro Wax & Tune
#
# - Meteo oraria Open-Meteo (3 giorni: ieri, oggi, giorno gara)
# - Stima temperatura neve per ora (snow_temp)
#   · filtro "memoria neve" sui 2 giorni precedenti
#   · influenza di:
#       - temperatura aria
#       - ombreggiatura (esposizione + orario + nuvolosità)
#       - vento
#       - nevicate recenti
# - Indici:
#   · shade_index 0–1 (0 pieno sole, 1 piena ombra / luce piatta)
#   · snow_moisture_index 0–1 (0 secca, 1 molto bagnata)
#   · glide_index 0–1 (scorrevolezza)
# - Funzione per derivare parametri di tuning dinamico
#   (snow_temp_c, snow_type) da passare a core.race_tuning.get_tuning_recommendation

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Any, Optional, List

import numpy as np
import requests
import streamlit as st

from .race_tuning import SnowType, Discipline, SkierLevel, TuningParamsInput

UA = {"User-Agent": "telemark-wax-pro/3.0"}


# ---------- chiamata Open-Meteo -------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def fetch_hourly_meteo(lat: float, lon: float, start: date, end: date) -> Optional[Dict[str, Any]]:
    """
    Meteo oraria per intervallo [start, end] (inclusi):
    - temperature_2m (°C)
    - relativehumidity_2m (%)
    - cloudcover (%)
    - windspeed_10m (km/h)
    - precipitation (mm)
    - snowfall (cm)
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(
            [
                "temperature_2m",
                "relativehumidity_2m",
                "cloudcover",
                "windspeed_10m",
                "precipitation",
                "snowfall",
            ]
        ),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "auto",
    }
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            headers=UA,
            timeout=12,
        )
        r.raise_for_status()
        js = r.json() or {}
        hourly = js.get("hourly")
        if not hourly:
            return None
        return hourly
    except Exception:
        return None


# ---------- utilità meteo / neve ------------------------------------------
def _shade_factor(aspect_deg: float, hour_local: float, cloudcover: Optional[float]) -> float:
    """
    Restituisce un indice 0–1:
      0 = pieno sole
      1 = piena ombra / luce piatta
    Usa:
      - esposizione versante (deg)
      - orario locale
      - nuvolosità (%)
    """
    d = aspect_deg % 360

    # base da esposizione + orario (simile a dem_tools, ma in forma numerica)
    # pendii N / NE hanno più ombra, S / SW più sole
    base = 0.5

    # mattina
    if hour_local < 10.0:
        # pendii E / SE più al sole
        if 60 <= d <= 150:
            base = 0.1
        elif 240 <= d <= 330:
            base = 0.9
        else:
            base = 0.6
    # metà giornata
    elif 10.0 <= hour_local <= 14.0:
        if (315 <= d <= 360) or (0 <= d <= 45):
            base = 0.8  # versante nord
        elif 135 <= d <= 225:
            base = 0.2  # sud
        else:
            base = 0.5
    # pomeriggio
    else:
        if 210 <= d <= 300:
            base = 0.2  # SO / O al sole
        elif 30 <= d <= 150:
            base = 0.8  # NE / E in ombra
        else:
            base = 0.5

    # nuvolosità: se cielo coperto avvicino a luce piatta (0.7–0.9)
    if cloudcover is None:
        return float(np.clip(base, 0.0, 1.0))

    cc = float(cloudcover)
    if cc >= 85:
        return float(np.clip(0.8, 0.0, 1.0))
    if 50 <= cc < 85:
        return float(np.clip((base + 0.6) / 2.0, 0.0, 1.0))
    return float(np.clip(base, 0.0, 1.0))


def _snow_temp_series(
    times: List[datetime],
    temp_air: List[float],
    cloudcover: List[float],
    windspeed: List[float],
    precip: List[float],
    snowfall: List[float],
    aspect_deg: float,
) -> np.ndarray:
    """
    Modello semplice ma "fisico" di temperatura neve:
    - memoria su più ore e giorni
    - dipendente da aria, sole/ombra, vento, neve fresca
    """
    n = len(times)
    if n == 0:
        return np.array([])

    temp_air = np.array(temp_air, dtype=float)
    cloudcover = np.array(cloudcover, dtype=float)
    windspeed = np.array(windspeed, dtype=float)
    precip = np.array(precip, dtype=float)
    snowfall = np.array(snowfall, dtype=float)

    # stima se ci sono state nevicate significative negli ultimi 24h
    # (più neve fresca -> neve che segue più velocemente l'aria)
    last_24_mask = (times >= (times[-1] - timedelta(hours=24)))
    fresh_snow_mm = float(np.nansum(np.where(last_24_mask, snowfall, 0.0)))
    fresh_factor = 1.0 + min(fresh_snow_mm / 10.0, 1.0) * 0.5  # fino a +50%

    # inizializzo neve come media fra minima degli ultimi 2 giorni e 0°C (limitata a 0, non oltre)
    min_recent = float(np.nanmin(temp_air)) if np.isfinite(temp_air).any() else -5.0
    snow_t0 = min(0.0, (min_recent * 0.7))  # neve tende a stare sotto lo zero
    snow = np.zeros(n, dtype=float)
    snow[0] = snow_t0

    for i in range(1, n):
        Ta = temp_air[i]
        # orario locale (uso ora dal timestamp)
        hour_local = times[i].hour + times[i].minute / 60.0
        cc = cloudcover[i] if np.isfinite(cloudcover[i]) else None
        w = windspeed[i] if np.isfinite(windspeed[i]) else 0.0

        shade = _shade_factor(aspect_deg, hour_local, cc)
        # 0 sole, 1 ombra → fattore di irraggiamento inverso
        sun_gain = 1.0 - shade  # 0 (buio) – 1 (sole pieno)

        # coefficiente di rilassamento neve verso l'aria:
        # · più alto con neve fresca
        # · più alto con sole
        alpha = 0.08 * fresh_factor + 0.04 * sun_gain

        # raffreddamento da vento (venti forti aumentano scambio)
        wind_cool = min(w / 40.0, 1.0) * 0.5  # fino a -0.5°C/h equivalente

        # update: low-pass su aria + contributo sole + effetto vento
        prev = snow[i - 1]
        target = Ta
        new = prev + alpha * (target - prev) - wind_cool

        # neve non sale oltre 0°C (soprattutto in gara su pista preparata)
        new = min(new, 0.0)

        snow[i] = new

    return snow


def _snow_moisture_index(
    snow_temp: np.ndarray,
    rh: np.ndarray,
    precip: np.ndarray,
    snowfall: np.ndarray,
) -> np.ndarray:
    """
    Indice 0–1 di "bagnato neve":
    - vicino a 0 con neve molto fredda e aria secca
    - vicino a 1 se neve è vicina a 0°C, alta umidità, o precipitazioni liquide
    """
    n = len(snow_temp)
    if n == 0:
        return np.array([])

    # 1) contributo da temperatura neve (0 se <= -12, 1 se >= 0)
    t = np.clip((snow_temp + 12.0) / 12.0, 0.0, 1.0)

    # 2) contributo da umidità relativa (0 se <= 40%, 1 se >= 95)
    rh = np.where(np.isfinite(rh), rh, 60.0)
    h = np.clip((rh - 40.0) / 55.0, 0.0, 1.0)

    # 3) precipitazioni: pioggia aumenta molto, neve un po' meno
    precip = np.where(np.isfinite(precip), precip, 0.0)
    snowfall = np.where(np.isfinite(snowfall), snowfall, 0.0)

    rain_effect = np.clip(precip / 2.0, 0.0, 1.0)  # >2 mm/h = contributo pieno
    snow_effect = np.clip(snowfall / 3.0, 0.0, 0.6)  # neve fresca inumidisce i primi cm

    # combinazione pesata
    m = 0.5 * t + 0.3 * h + 0.4 * rain_effect + 0.2 * snow_effect
    return np.clip(m, 0.0, 1.0)


def _glide_index(snow_temp: np.ndarray, moisture: np.ndarray) -> np.ndarray:
    """
    Indice 0–1 di "scorrevolezza" teorica:
    - troppo fredda e secca → meno glide
    - troppo bagnata → freno
    - mezzo (intorno a -8/-2, umidità media) → massimo glide
    """
    n = len(snow_temp)
    if n == 0:
        return np.array([])

    # penalità per temperature troppo estreme
    # optimum zone: -10 .. -2
    t = snow_temp
    # scala a 0–1: 1 se in [-10, -2], degradando fuori
    t_score = np.clip(1.0 - np.abs((t + 6.0) / 6.0), 0.0, 1.0)

    m = moisture  # 0 secca, 1 molto bagnata
    # optimum moisture ~0.4–0.6
    m_score = 1.0 - np.abs(m - 0.5) * 2.0
    m_score = np.clip(m_score, 0.0, 1.0)

    g = 0.6 * t_score + 0.4 * m_score
    return np.clip(g, 0.0, 1.0)


@dataclass
class MeteoProfile:
    times: List[datetime]
    temp_air: np.ndarray
    rh: np.ndarray
    cloudcover: np.ndarray
    windspeed: np.ndarray
    precip: np.ndarray
    snowfall: np.ndarray
    snow_temp: np.ndarray
    shade_index: np.ndarray
    snow_moisture_index: np.ndarray
    glide_index: np.ndarray


def build_meteo_profile_for_race_day(ctx: Dict[str, Any]) -> Optional[MeteoProfile]:
    """
    Costruisce profilo meteo completo per la giornata di gara:
    - se ctx["race_datetime"] esiste → usa quella data,
      altrimenti usa oggi come fallback.
    - prende meteo da 2 giorni prima fino al giorno gara (memoria neve).
    - profilo restituito solo per il giorno gara (0–23h).
    """
    lat = float(ctx.get("lat", 45.83333))
    lon = float(ctx.get("lon", 7.73333))
    race_dt = ctx.get("race_datetime")

    if isinstance(race_dt, datetime):
        race_day = race_dt.date()
    else:
        race_day = datetime.utcnow().date()

    start = race_day - timedelta(days=2)
    end = race_day

    hourly = fetch_hourly_meteo(lat, lon, start, end)
    if hourly is None:
        return None

    times_str = hourly.get("time") or []
    if not times_str:
        return None

    # trasformo in datetime
    times = [datetime.fromisoformat(t) for t in times_str]

    def arr(name: str, fill: float = np.nan) -> np.ndarray:
        vals = hourly.get(name) or []
        if not vals:
            return np.full(len(times), fill, dtype=float)
        return np.array(vals, dtype=float)

    temp_air = arr("temperature_2m")
    rh = arr("relativehumidity_2m")
    cloud = arr("cloudcover")
    wind = arr("windspeed_10m")
    precip = arr("precipitation")
    snowfall = arr("snowfall")

    # filtro solo il giorno gara (ma TENENDO in considerazione full serie per memoria neve)
    mask_race = np.array([t.date() == race_day for t in times])
    if not mask_race.any():
        return None

    # aspetto versante: se ctx non lo ha, assumo Nord-Ovest (classico ombreggiato)
    aspect_deg = float(ctx.get("aspect_deg", 330.0))

    # serie completa neve (su 3 giorni)
    snow_full = _snow_temp_series(
        times=times,
        temp_air=temp_air,
        cloudcover=cloud,
        windspeed=wind,
        precip=precip,
        snowfall=snowfall,
        aspect_deg=aspect_deg,
    )

    # subset solo giorno gara
    times_r = [t for t, m in zip(times, mask_race) if m]
    Ta_r = temp_air[mask_race]
    rh_r = rh[mask_race]
    cc_r = cloud[mask_race]
    wind_r = wind[mask_race]
    precip_r = precip[mask_race]
    snowfall_r = snowfall[mask_race]
    snow_r = snow_full[mask_race]

    # shade index per giorno gara
    shade_r = []
    for t, cc_val in zip(times_r, cc_r):
        h = t.hour + t.minute / 60.0
        cc_val_f = float(cc_val) if np.isfinite(cc_val) else None
        shade_r.append(_shade_factor(aspect_deg, h, cc_val_f))
    shade_r = np.array(shade_r, dtype=float)

    # indici umidità neve & scorrevolezza
    moisture_r = _snow_moisture_index(snow_r, rh_r, precip_r, snowfall_r)
    glide_r = _glide_index(snow_r, moisture_r)

    return MeteoProfile(
        times=times_r,
        temp_air=Ta_r,
        rh=rh_r,
        cloudcover=cc_r,
        windspeed=wind_r,
        precip=precip_r,
        snowfall=snowfall_r,
        snow_temp=snow_r,
        shade_index=shade_r,
        snow_moisture_index=moisture_r,
        glide_index=glide_r,
    )


# ---------- tuning dinamico basato su meteo -------------------------------
@dataclass
class DynamicTuningResult:
    input_params: TuningParamsInput
    snow_type: SnowType
    summary: str  # testo descrittivo da mostrare in UI


def _classify_snow_type_from_profile(
    snow_temp_c: float,
    moisture_idx: float,
    injected: bool,
) -> SnowType:
    """
    Traduzione profilo in SnowType logico.
    """
    if injected:
        return SnowType.ICE

    if snow_temp_c <= -8.0 and moisture_idx < 0.3:
        return SnowType.DRY
    if -8.0 < snow_temp_c <= -2.0 and moisture_idx < 0.6:
        return SnowType.PACKED
    if snow_temp_c > -2.0 and moisture_idx >= 0.5:
        return SnowType.WET

    # fallback generico
    return SnowType.PACKED


def build_dynamic_tuning_for_race(
    profile: MeteoProfile,
    ctx: Dict[str, Any],
    discipline: Discipline,
    skier_level: SkierLevel,
    injected: bool = False,
) -> Optional[DynamicTuningResult]:
    """
    Usa il profilo meteo del giorno gara e il contesto per costruire
    parametri di tuning dinamico:
      - snow_temp_c = temperatura neve stimata all'ora di gara
      - snow_type   = tipologia neve da profilo
    """
    race_dt = ctx.get("race_datetime")
    if not isinstance(race_dt, datetime):
        return None

    # trova l'indice orario più vicino all'ora di gara
    best_idx = None
    best_diff = 9999.0
    for i, t in enumerate(profile.times):
        diff = abs((t - race_dt).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_idx = i

    if best_idx is None:
        return None

    snow_temp_c = float(profile.snow_temp[best_idx])
    temp_air_c = float(profile.temp_air[best_idx])
    rh = float(profile.rh[best_idx])
    cloud = float(profile.cloudcover[best_idx])
    shade_idx = float(profile.shade_index[best_idx])
    moisture = float(profile.snow_moisture_index[best_idx])
    glide = float(profile.glide_index[best_idx])
    wind = float(profile.windspeed[best_idx])

    snow_type = _classify_snow_type_from_profile(
        snow_temp_c=snow_temp_c,
        moisture_idx=moisture,
        injected=injected,
    )

    params = TuningParamsInput(
        discipline=discipline,
        snow_temp_c=snow_temp_c,
        air_temp_c=temp_air_c,
        snow_type=snow_type,
        injected=injected,
        skier_level=skier_level,
    )

    # breve sintesi
    shade_txt = (
        "molto in ombra"
        if shade_idx > 0.7
        else "parzialmente in ombra"
        if shade_idx > 0.4
        else "abbastanza soleggiata"
    )
    moisture_txt = (
        "molto secca"
        if moisture < 0.25
        else "leggermente secca"
        if moisture < 0.4
        else "compatta / neutra"
        if moisture < 0.6
        else "umida"
        if moisture < 0.8
        else "molto bagnata"
    )
    glide_txt = (
        "molto scorrevole"
        if glide > 0.75
        else "buona scorrevolezza"
        if glide > 0.55
        else "scorrevolezza media"
        if glide > 0.35
        else "scorrevolezza limitata"
    )

    summary = (
        f"Alle {race_dt.strftime('%H:%M')} la neve stimata è ~{snow_temp_c:.1f} °C "
        f"(aria {temp_air_c:.1f} °C), pista {shade_txt}, neve {moisture_txt}, "
        f"vento ~{wind:.1f} km/h, scorrevolezza {glide_txt}."
    )

    return DynamicTuningResult(
        input_params=params,
        snow_type=snow_type,
        summary=summary,
    )
