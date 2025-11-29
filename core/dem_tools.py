# core/dem_tools.py
# Telemark · Pro Wax & Tune – DEM V7
#
# Questo modulo:
#  - Recupera quota da ESRI → OpenTopo → fallback
#  - Calcola esposizione e pendenza con filtro
#  - Disegna chart Altair in Streamlit
#  - Fornisce punti con quota per POV 3D
#
# NON mostra mappe. Serve solo calcolo + grafici.

from __future__ import annotations

import math
import requests
import streamlit as st
import pandas as pd
import altair as alt
from typing import Any, Dict, List, Tuple


UA = {"User-Agent": "telemark-dem/3.1"}


# ---------------------------------------------------------------------
# DEM SOURCES
# ---------------------------------------------------------------------
def _esri_elevation(lat: float, lon: float) -> float | None:
    """Esri World Elevation (best quality)."""
    url = (
        "https://elevation.arcgis.com/arcgis/rest/services/Tools/ElevationSync/"
        "GPServer/Profile/execute"
    )
    payload = {
        "InputLineFeatures": {
            "features": [
                {
                    "geometry": {
                        "paths": [[[lon, lat], [lon, lat]]],
                        "spatialReference": {"wkid": 4326},
                    }
                }
            ],
            "geometryType": "esriGeometryPolyline",
        },
        "ProfileIDField": "",
        "MaximumSampleDistance": {"distance": 5, "units": "esriMeters"},
        "returnZ": "true",
        "f": "json",
    }
    try:
        r = requests.post(url, json=payload, timeout=6, headers=UA)
        js = r.json()
        rows = js.get("results", [{}])[0].get("value", {}).get("features", [])
        if rows:
            attrs = rows[0].get("attributes", {})
            z = attrs.get("HEIGHT")
            return float(z) if z is not None else None
    except Exception:
        return None
    return None


def _opentopo_elevation(lat: float, lon: float) -> float | None:
    """OpenTopo DEM (fallback)."""
    url = f"https://api.opentopodata.org/v1/test-dataset?locations={lat},{lon}"
    try:
        r = requests.get(url, timeout=6, headers=UA)
        js = r.json()
        res = js.get("results", [{}])[0]
        h = res.get("elevation")
        return float(h) if h is not None else None
    except Exception:
        return None


def get_elevation(lat: float, lon: float) -> float:
    """DEM ibrido robusto."""
    for fn in (_esri_elevation, _opentopo_elevation):
        h = fn(lat, lon)
        if h is not None:
            return h
    return 0.0


# ---------------------------------------------------------------------
# SLOPE & ASPECT
# ---------------------------------------------------------------------
def _slope_aspect(lat: float, lon: float, step_m: float = 18.0) -> Tuple[float, float]:
    """
    Calcola pendenza (°) e esposizione (°) usando 8 sample attorno.
    """
    dlat = step_m / 111320
    dlon = step_m / (40075000 * math.cos(math.radians(lat)) / 360)

    samples = []
    for dy in (-dlat, 0, dlat):
        for dx in (-dlon, 0, dlon):
            la = lat + dy
            lo = lon + dx
            samples.append((la, lo, get_elevation(la, lo)))

    # griglia 3x3
    z = [s[2] for s in samples]
    if len(z) != 9:
        return 0.0, 0.0

    # pendenza
    dzdx = ((z[2] + z[5] + z[8]) - (z[0] + z[3] + z[6])) / (6 * step_m)
    dzdy = ((z[6] + z[7] + z[8]) - (z[0] + z[1] + z[2])) / (6 * step_m)

    slope = math.degrees(math.atan(math.sqrt(dzdx**2 + dzdy**2)))

    # esposizione
    if dzdx == 0 and dzdy == 0:
        aspect = 0.0
    else:
        aspect = math.degrees(math.atan2(dzdx, dzdy))
        aspect = (aspect + 360) % 360

    return slope, aspect


def _aspect_label(angle: float) -> str:
    dirs = [
        (0, "N"),
        (45, "NE"),
        (90, "E"),
        (135, "SE"),
        (180, "S"),
        (225, "SW"),
        (270, "W"),
        (315, "NW"),
    ]
    best = min(dirs, key=lambda x: abs(x[0] - angle))
    return best[1]


# ---------------------------------------------------------------------
# ALTITUDE PROFILING for POV3D
# ---------------------------------------------------------------------
def add_elevation_to_polyline(points: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """Aggiunge 'ele' a ogni punto (lento ma accurato)."""
    out = []
    for p in points:
        h = get_elevation(p["lat"], p["lon"])
        out.append({"lat": p["lat"], "lon": p["lon"], "ele": h})
    return out


# ---------------------------------------------------------------------
# STREAMLIT VIEW (giorno)
# ---------------------------------------------------------------------
def render_dem(T: Dict[str, Any], ctx: Dict[str, Any]) -> None:
    """Mostra DEM (pendenza/esposizione) attorno al punto selezionato."""

    lat = float(ctx.get("marker_lat", ctx.get("lat", 45.83333)))
    lon = float(ctx.get("marker_lon", ctx.get("lon", 7.73333)))

    with st.spinner("Calcolo esposizione & pendenza…"):
        slope, aspect = _slope_aspect(lat, lon)
        elev = get_elevation(lat, lon)

    df = pd.DataFrame(
        {
            "metric": ["Quota (m)", "Pendenza (°)", "Esposizione (°)"],
            "value": [elev, slope, aspect],
        }
    )

    cA, cB, cC = st.columns(3)
    cA.metric("Quota", f"{elev:.0f} m")
    cB.metric("Pendenza", f"{slope:.1f}°")
    cC.metric("Esposizione", f"{_aspect_label(aspect)} ({aspect:.0f}°)")


# ---------------------------------------------------------------------
# PER POV 3D: restituisce DEM lungo una pista
# ---------------------------------------------------------------------
def build_dem_profile_for_pov(points: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """Ritorna polyline con quota reale (ele) per POV 3D."""
    return add_elevation_to_polyline(points)
