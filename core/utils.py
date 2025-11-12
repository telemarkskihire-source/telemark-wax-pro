# core/utils.py
# Utilità condivise: meteo/termo, conversioni, emoji bandiere

from __future__ import annotations
import math
import numpy as np

__all__ = [
    "rh_from_t_td", "wetbulb_stull",
    "c_to_f", "f_to_c", "ms_to_kmh", "kmh_to_ms",
    "flag",
]

# ---------- conversioni ----------
def c_to_f(x: float | np.ndarray) -> float | np.ndarray:
    return np.asarray(x, dtype=float) * 9.0 / 5.0 + 32.0

def f_to_c(x: float | np.ndarray) -> float | np.ndarray:
    return (np.asarray(x, dtype=float) - 32.0) * 5.0 / 9.0

def ms_to_kmh(x: float | np.ndarray) -> float | np.ndarray:
    return np.asarray(x, dtype=float) * 3.6

def kmh_to_ms(x: float | np.ndarray) -> float | np.ndarray:
    return np.asarray(x, dtype=float) / 3.6

# ---------- psicrometria ----------
def rh_from_t_td(Tv, Td):
    """
    UR (%) da temperatura aria (°C) e dew point (°C).
    Formula Magnus-Tetens, clamp 1..100.
    """
    Tv = np.asarray(Tv, dtype=float)
    Td = np.asarray(Td, dtype=float)
    a, b = 17.625, 243.04
    es = 6.1094 * np.exp((a * Tv) / (b + Tv))
    e  = 6.1094 * np.exp((a * Td) / (b + Td))
    RH = 100.0 * (e / es)
    return np.clip(RH, 1.0, 100.0)

def wetbulb_stull(Tv, RH):
    """
    Wet-bulb (°C) approssimato (Stull 2011).
    Tv in °C, RH in % (1..100). Restituisce array float.
    """
    Tv = np.asarray(Tv, dtype=float)
    RH = np.clip(np.asarray(RH, dtype=float), 1.0, 100.0)
    Tw = (
        Tv * np.arctan(0.151977 * np.sqrt(RH + 8.313659))
        + np.arctan(Tv + RH)
        - np.arctan(RH - 1.676331)
        + 0.00391838 * (RH ** 1.5) * np.arctan(0.023101 * RH)
        - 4.686035
    )
    return Tw

# ---------- bandiere ----------
def flag(cc: str | None) -> str:
    """Da ISO2 a emoji bandiera; fallback bianco."""
    try:
        if not cc:
            return "🏳️"
        c = cc.upper()
        return chr(127397 + ord(c[0])) + chr(127397 + ord(c[1]))
    except Exception:
        return "🏳️"
