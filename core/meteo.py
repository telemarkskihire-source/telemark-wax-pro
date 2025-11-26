# core/meteo.py
# Meteo avanzata per Telemark · Pro Wax & Tune
#
# - Meteo oraria Open-Meteo (3 giorni: ieri, oggi, giorno gara)
# - Stima temperatura neve per ora (snow_temp)
#   · memoria neve sui 2 giorni precedenti
#   · influenza di:
#       - temperatura aria
#       - ombreggiatura (esposizione + orario + nuvolosità)
#       - vento
#       - nevicate recenti
# - Indici:
#   · shade_index 0–1 (0 pieno sole, 1 piena ombra / luce piatta)
#   · snow_moisture_index 0–1 (0 secca, 1 molto bagnata)
#   · glide_index 0–1 (scorrevolezza)
# - VLT consigliato (visible light transmission) per la maschera:
#   · vlt_percent + categoria (S0–S4) in base a luce/ombra e nuvole
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
def fetch_hourly_meteo(
    lat: float,
    lon: float,
    start: date,
    end: date,
) -> Optional[Dict[str, Any]]:
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
def _shade_factor(
    aspect_deg: float,
    hour_local: float,
    cloudcover: Optional[float],
) -> float:
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

    # base da esposizione + orario
    base = 0.5

    # mattina
    if hour_local < 10.0:
        if 60 <= d <= 150:
            base = 0.1           # E/SE al sole
        elif 240 <= d <= 330:
            base = 0.9           # O/NO in ombra
        else:
            base = 0.6
    # metà giornata
    elif 10.0 <= hour_local <= 14.0:
        if (315 <= d <= 360) or (0 <= d <= 45):
            base = 0.8           # N
        elif 135 <= d <= 225:
            base = 0.2           # S
        else:
            base = 0.5
    # pomeriggio
    else:
        if 210 <= d <= 300:
            base = 0.2           # SO/O al sole
        elif 30 <= d <= 150:
            base = 0.8           # NE/E in ombra
        else:
            base = 0.5

    # nuvolosità → avvicino verso luce piatta
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
    Modello temperatura neve:
    - memoria su più ore/giorni
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

    # maschera ultime 24h → serve per valutare neve fresca
    if n == 1:
        last_24_mask = np.array([True], dtype=bool)
    else:
        ref_time = times[-1] - timedelta(hours=24)
        last_24_mask = np.array([t >= ref_time for t in times], dtype=bool)

    fresh_snow_mm = float(np.nansum(np.where(last_24_mask, snowfall, 0.0)))
    # più neve fresca → neve "segue" più l'aria
    fresh_factor = 1.0 + min(fresh_snow_mm / 10.0, 1.0) * 0.5  # fino a +50%

    # inizializzo neve: media fra minima aria ultimi giorni e 0°C (limitata a 0)
    if np.isfinite(temp_air).any():
        min_recent = float(np.nanmin(temp_air))
    else:
        min_recent = -5.0
    snow_t0 = min(0.0, (min_recent * 0.7))
    snow = np.zeros(n, dtype=float)
    snow[0] = snow_t0

    for i in range(1, n):
        Ta = temp_air[i]
        # orario locale
        hour_local = times[i].hour + times[i].minute / 60.0
        cc = cloudcover[i] if np.isfinite(cloudcover[i]) else None
        w = windspeed[i] if np.isfinite(windspeed[i]) else 0.0

        shade = _shade_factor(aspect_deg, hour_local, cc)
        sun_gain = 1.0 - shade  # 0 (buio) – 1 (sole pieno)

        # coefficiente di rilassamento neve → aria
        alpha = 0.08 * fresh_factor + 0.04 * sun_gain

        # raffreddamento vento
        wind_cool = min(w / 40.0, 1.0) * 0.5  # fino a -0.5 °C/h

        prev = snow[i - 1]
        target = Ta
        new = prev + alpha * (target - prev) - wind_cool

        # neve non oltre 0 °C
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
    Indice 0–1 "bagnato neve":
    - 0 neve molto fredda + aria secca
    - 1 neve vicino a 0°C + UR alta + pioggia
    """
    n = len(snow_temp)
    if n == 0:
        return np.array([])

    # 1) contributo da T neve (0 se <= -12, 1 se >= 0)
    t = np.clip((snow_temp + 12.0) / 12.0, 0.0, 1.0)

    # 2) umidità relativa
    rh = np.where(np.isfinite(rh), rh, 60.0)
    h = np.clip((rh - 40.0) / 55.0, 0.0, 1.0)

    # 3) precipitazioni
    precip = np.where(np.isfinite(precip), precip, 0.0)
    snowfall = np.where(np.isfinite(snowfall), snowfall, 0.0)

    rain_effect = np.clip(precip / 2.0, 0.0, 1.0)      # >2 mm/h pieno effetto
    snow_effect = np.clip(snowfall / 3.0, 0.0, 0.6)    # neve fresca inumidisce un po'

    m = 0.5 * t + 0.3 * h + 0.4 * rain_effect + 0.2 * snow_effect
    return np.clip(m, 0.0, 1.0)


def _glide_index(
    snow_temp: np.ndarray,
    moisture: np.ndarray,
) -> np.ndarray:
    """
    Indice 0–1 di "scorrevolezza" teorica:
    - troppo fredda/secca o troppo bagnata → meno glide
    - medio (circa -10/-2 e umidità media) → massimo glide
    """
    n = len(snow_temp)
    if n == 0:
        return np.array([])

    # optimum T: -10 .. -2
    t = snow_temp
    t_score = np.clip(1.0 - np.abs((t + 6.0) / 6.0), 0.0, 1.0)

    # optimum moisture ~0.4–0.6
    m = moisture
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
    Profilo meteo completo per la giornata di gara:
    - se ctx["race_datetime"] esiste → usa quella data,
      altrimenti usa oggi.
    - prende meteo da 2 giorni prima fino al giorno gara
      (memoria neve).
    - ritorna solo ore del giorno gara (00–24).
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

    # maschera solo giorno gara
    mask_race = np.array([t.date() == race_day for t in times], dtype=bool)
    if not mask_race.any():
        return None

    # esposizione versante: se non esiste → NNO tipico
    aspect_deg = float(ctx.get("aspect_deg", 330.0))

    # serie completa neve (3 giorni) per memoria
    snow_full = _snow_temp_series(
        times=times,
        temp_air=temp_air,
        cloudcover=cloud,
        windspeed=wind,
        precip=precip,
        snowfall=snowfall,
        aspect_deg=aspect_deg,
    )

    # subset giorno gara
    times_r = [t for t, m in zip(times, mask_race) if m]
    Ta_r = temp_air[mask_race]
    rh_r = rh[mask_race]
    cc_r = cloud[mask_race]
    wind_r = wind[mask_race]
    precip_r = precip[mask_race]
    snowfall_r = snowfall[mask_race]
    snow_r = snow_full[mask_race]

    # shade index per ogni ora gara
    shade_r = []
    for t, cc_val in zip(times_r, cc_r):
        h = t.hour + t.minute / 60.0
        cc_val_f = float(cc_val) if np.isfinite(cc_val) else None
        shade_r.append(_shade_factor(aspect_deg, h, cc_val_f))
    shade_r = np.array(shade_r, dtype=float)

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
    summary: str          # testo descrittivo per UI
    vlt_percent: float    # VLT consigliato (0–100 %)
    vlt_category: str     # es. "S2 (20%) – sole moderato"


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

    return SnowType.PACKED


def _suggest_vlt(
    shade_idx: float,
    cloudcover_pct: float,
) -> tuple[float, str]:
    """
    Stima VLT consigliato in base a luminosità:
    - combina ombreggiatura (shade_idx) e nuvolosità
    - ritorna (percentuale, categoria S0–S4)
    """
    # 0 = buio, 1 = luce fortissima
    brightness = (1.0 - shade_idx) * (1.0 - cloudcover_pct / 100.0)
    brightness = float(np.clip(brightness, 0.0, 1.0))

    if brightness >= 0.8:
        vlt = 10.0
        cat = "S3–S4 (~10% VLT, molto scuro)"
    elif brightness >= 0.6:
        vlt = 20.0
        cat = "S2 (~20% VLT, sole pieno)"
    elif brightness >= 0.4:
        vlt = 30.0
        cat = "S1–S2 (~30% VLT, luce media)"
    elif brightness >= 0.25:
        vlt = 40.0
        cat = "S1 (~40% VLT, cielo velato)"
    else:
        vlt = 60.0
        cat = "S0–S1 (50–70% VLT, luce piatta / notturna)"

    return vlt, cat


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
      - vlt_percent = VLT consigliato per la maschera
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

    vlt_percent, vlt_cat = _suggest_vlt(shade_idx, cloud)

    params = TuningParamsInput(
        discipline=discipline,
        snow_temp_c=snow_temp_c,
        air_temp_c=temp_air_c,
        snow_type=snow_type,
        injected=injected,
        skier_level=skier_level,
    )

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
        f"vento ~{wind:.1f} km/h, scorrevolezza {glide_txt} "
        f"(UR {rh:.0f}%, copertura nuvolosa {cloud:.0f}%, "
        f"VLT consigliato ≈ {vlt_percent:.0f}% – {vlt_cat})."
    )

    return DynamicTuningResult(
        input_params=params,
        snow_type=snow_type,
        summary=summary,
        vlt_percent=vlt_percent,
        vlt_category=vlt_cat,
    )
