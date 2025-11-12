# core/utils.py
# Utilità condivise (meteo, fisica semplice, UA)

import math
import numpy as np

# User-Agent coerente per tutte le chiamate HTTP
UA = {"User-Agent": "telemark-wax-pro/1.2 (+https://telemarkskihire.com)"}

# --- Umidità relativa da T e Td (°C) ---
def rh_from_t_td(Tv, Td):
    """
    Tv: temperatura aria [°C]
    Td: dew point [°C]
    return: UR [%] (clippata 1..100)
    """
    Tv = np.array(Tv, dtype=float)
    Td = np.array(Td, dtype=float)
    a, b = 17.625, 243.04
    es = 6.1094 * np.exp((a * Tv) / (b + Tv))
    e  = 6.1094 * np.exp((a * Td) / (b + Td))
    RH = 100.0 * (e / es)
    return np.clip(RH, 1, 100)

# --- Wet-bulb (formula di Stull) ---
def wetbulb_stull(Tv, RH):
    """
    Tv [°C], RH [%] -> Tw [°C]
    """
    RH = np.clip(RH, 1, 100)
    Tw = (
        Tv * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
        + np.arctan(Tv + RH)
        - np.arctan(RH - 1.676331)
        + 0.00391838 * (RH ** 1.5) * np.arctan(0.023101 * RH)
        - 4.686035
    )
    return Tw

# --- Geometria solare minimale + cielo sereno GHI ---
def _solar_declination(day_of_year):
    return 23.45 * math.pi / 180 * math.sin(2 * math.pi * (284 + day_of_year) / 365)

def _solar_cos_zenith(lat_deg, lon_deg, ts_utc):
    latr = math.radians(lat_deg)
    # approssimazione: ora solare locale ≈ ora UTC + lon/15
    frac_day = (ts_utc.hour + ts_utc.minute / 60) + lon_deg / 15
    H = math.radians(15 * (frac_day - 12))
    delta = _solar_declination(ts_utc.timetuple().tm_yday)
    cosz = math.sin(latr) * math.sin(delta) + math.cos(latr) * math.cos(delta) * math.cos(H)
    return max(0.0, cosz)

def clear_sky_ghi(lat, lon, ts_utc):
    """GHI cielo sereno [W/m²] molto semplice (serve solo come driver relativo)."""
    S0 = 1361.0
    cosz = _solar_cos_zenith(lat, lon, ts_utc)
    return max(0.0, S0 * cosz * 0.75)

# --- Vento "effettivo" per scambio ---
def effective_wind(w):
    w = np.clip(w, 0, 8.0)  # limita per evitare outlier
    return 8.0 * (np.log1p(w) / np.log1p(8.0))

# (Opzionali, utili in altri moduli)
def c_to_f(x): return x * 9 / 5 + 32
def ms_to_kmh(x): return x * 3.6

__all__ = [
    "UA", "rh_from_t_td", "wetbulb_stull",
    "clear_sky_ghi", "effective_wind",
    "c_to_f", "ms_to_kmh",
]
