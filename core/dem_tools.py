# core/dem_tools.py
# DEM & pendenza per Telemark · Pro Wax & Tune
#
# - Usa API Open-Meteo /elevation per un piccolo grid attorno al punto
# - Calcola:
#     · quota media nel intorno
#     · pendenza (gradi) dal gradiente centrale
#     · esposizione (aspet) in gradi e come stringa N/NE/.../W
# - Rende in Streamlit tre valori:
#     · Quota
#     · Pendenza
#     · Esposizione
# - Usa ctx["marker_lat"/"marker_lon"] se presenti, altrimenti ctx["lat"/"lon"]

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List

import requests
import numpy as np
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/2.2"}


@dataclass
class DEMSample:
    lat: float
    lon: float
    elevation_m: float


# ----------------------------------------------------------------------
# Helper geografici
# ----------------------------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Ritorna bearing geodetico (0 = Nord, 90 = Est) in gradi.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        dlambda
    )
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _aspect_to_label(aspect_deg: float) -> str:
    """
    Converte esposizione (0 = N, 90 = E) in label N/NE/E/...
    """
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int(((aspect_deg + 22.5) % 360) / 45.0)
    return dirs[idx]


# ----------------------------------------------------------------------
# DEM sampling con Open-Meteo
# ----------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def _sample_dem_grid(
    lat: float,
    lon: float,
    size: int = 5,
    spacing_m: float = 30.0,
) -> Tuple[np.ndarray, float]:
    """
    Sample DEM su una griglia size×size attorno a (lat, lon).

    Ritorna:
      - elev_grid (size×size) in metri
      - spacing effettivo in metri fra i punti adiacenti
    """
    if size % 2 == 0:
        size += 1  # vogliamo size dispari (per avere centro esatto)

    half = size // 2

    # conversione metri -> gradi (approx)
    dlat = spacing_m / 111320.0
    dlon = spacing_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))

    lats: List[float] = []
    lons: List[float] = []
    for j in range(size):
        for i in range(size):
            lats.append(lat + (j - half) * dlat)
            lons.append(lon + (i - half) * dlon)

    params = {
        "latitude": ",".join(f"{x:.6f}" for x in lats),
        "longitude": ",".join(f"{x:.6f}" for x in lons),
    }

    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params=params,
            headers=UA,
            timeout=10,
        )
        r.raise_for_status()
        js = r.json() or {}
        elev = js.get("elevation", [])
        if not elev or len(elev) != len(lats):
            raise RuntimeError("elevation data mismatch")
    except Exception:
        # fallback: griglia piatta a quota 0
        elev = [0.0] * (size * size)

    elev_arr = np.array(elev, dtype=float).reshape((size, size))

    # distanza effettiva fra centro e cella centrale a Est (per sicurezza)
    center_lat = lat
    center_lon = lon
    east_lat = lat
    east_lon = lon + dlon
    spacing_eff = _haversine_m(center_lat, center_lon, east_lat, east_lon)

    return elev_arr, float(spacing_eff)


def _compute_slope_aspect(
    elev: np.ndarray,
    spacing_m: float,
) -> Tuple[float, float]:
    """
    Calcola pendenza (gradi) ed esposizione (gradi da Nord) dal grid elev.
    Usa differenze finite centrali sul centro della griglia.
    """
    h, w = elev.shape
    cy = h // 2
    cx = w // 2

    # gradienti centrali (N-S, E-W)
    dz_dy = (elev[cy + 1, cx] - elev[cy - 1, cx]) / (2.0 * spacing_m)
    dz_dx = (elev[cy, cx + 1] - elev[cy, cx - 1]) / (2.0 * spacing_m)

    # pendenza: arctan(sqrt(dx^2 + dy^2))
    grad_mag = math.sqrt(dz_dx ** 2 + dz_dy ** 2)
    slope_rad = math.atan(grad_mag)
    slope_deg = math.degrees(slope_rad)

    # clamp a valori sensati (0–75°)
    slope_deg = max(0.0, min(slope_deg, 75.0))

    # esposizione: direzione di massima discesa
    # attenzione ai segni: y cresce verso Sud nel grid
    # usiamo convenzione 0 = N, 90 = E
    if dz_dx == 0 and dz_dy == 0:
        aspect_deg = 0.0
    else:
        # gradient vector = (dz/dx East, dz/dy South)
        # direzione di massima pendenza in gradi da Nord:
        aspect_rad = math.atan2(dz_dx, dz_dy)  # x = Est, y = Sud
        aspect_deg = (math.degrees(aspect_rad) + 360.0) % 360.0

    return float(slope_deg), float(aspect_deg)


# ----------------------------------------------------------------------
# Render Streamlit
# ----------------------------------------------------------------------
def render_dem(T: Dict[str, str], ctx: Dict[str, Any]) -> None:
    """
    Calcola quota, pendenza ed esposizione per il punto selezionato
    e li mostra nella UI.

    Usa prima ctx["marker_lat"/"marker_lon"]; se mancanti,
    fallback su ctx["lat"/"lon"].
    """
    lat = float(ctx.get("marker_lat", ctx.get("lat", 45.83333)))
    lon = float(ctx.get("marker_lon", ctx.get("lon", 7.73333)))

    elev_grid, spacing_m = _sample_dem_grid(lat, lon, size=5, spacing_m=30.0)

    # quota: media nel riquadro 3×3 centrale
    h, w = elev_grid.shape
    cy = h // 2
    cx = w // 2
    center_patch = elev_grid[cy - 1 : cy + 2, cx - 1 : cx + 2]
    elev_center = float(np.nanmean(center_patch))

    slope_deg, aspect_deg = _compute_slope_aspect(elev_grid, spacing_m)
    aspect_label = _aspect_to_label(aspect_deg)

    # ---- UI ----
    col_q, col_s, col_a = st.columns(3)

    with col_q:
        st.metric("Quota", f"{elev_center:.0f} m")

    with col_s:
        st.metric("Pendenza", f"{slope_deg:.1f}°")

    with col_a:
        st.metric("Esposizione", f"{aspect_label} ({aspect_deg:.0f}°)")

    # Salviamo qualcosa nel contesto per possibili usi futuri
    ctx["dem_elevation_m"] = elev_center
    ctx["dem_slope_deg"] = slope_deg
    ctx["dem_aspect_deg"] = aspect_deg
    ctx["dem_aspect_label"] = aspect_label
