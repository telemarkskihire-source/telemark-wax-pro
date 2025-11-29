# core/dem_tools.py
# DEM ibrido: ESRI → SRTM fallback. Mapbox pronto ma disattivato.

from __future__ import annotations

import math
import numpy as np
import requests
import rasterio
from rasterio.io import MemoryFile
from typing import List, Tuple, Optional
import streamlit as st

UA = {"User-Agent": "telemark-wax-pro/3.0"}

# ---------------------------------------------------------
# Utilità coordinate
# ---------------------------------------------------------
def _valid_coord(lat: float, lon: float) -> bool:
    """Verifica che sia una coordinata realistica per Italia / Alpi."""
    return 35.0 < lat < 47.5 and 5.0 < lon < 13.5


def _bbox_from_polyline(
    poly: List[Tuple[float, float]],
    padding_m: float = 80.0,
) -> Optional[Tuple[float, float, float, float]]:
    """Bounding box con padding in metri."""
    if not poly:
        return None

    lats = [p[0] for p in poly]
    lons = [p[1] for p in poly]

    if not all(_valid_coord(lat, lon) for lat, lon in zip(lats, lons)):
        return None

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    pad_deg = padding_m / 111320.0
    return (
        min_lat - pad_deg,
        min_lon - pad_deg,
        max_lat + pad_deg,
        max_lon + pad_deg,
    )


# ---------------------------------------------------------
# DEM SOURCE 1 — ESRI WORLD ELEVATION 3D (molto stabile)
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_dem_esri(
    bbox: Tuple[float, float, float, float]
) -> Optional[np.ndarray]:

    min_lat, min_lon, max_lat, max_lon = bbox

    url = (
        "https://elevation.arcgis.com/arcgis/rest/services/"
        "WorldElevation/Terrain/ImageServer/exportImage"
    )

    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": "512,512",
        "format": "tiff",
        "pixelType": "F32",
        "f": "image",
    }

    try:
        r = requests.get(url, params=params, headers=UA, timeout=25)
        r.raise_for_status()
        if not r.content:
            return None
        with MemoryFile(r.content) as mem:
            with mem.open() as src:
                return src.read(1)
    except Exception:
        return None


# ---------------------------------------------------------
# DEM SOURCE 2 — SRTM fallback (open)
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_dem_srtm(
    bbox: Tuple[float, float, float, float]
) -> Optional[np.ndarray]:

    min_lat, min_lon, max_lat, max_lon = bbox

    url = (
        "https://s3.amazonaws.com/elevation-tiles-prod/skadi/"
        f"{int(min_lat)}_{int(min_lon)}.tif"
    )

    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        with MemoryFile(r.content) as mem:
            with mem.open() as src:
                data = src.read(1)
                return data
    except Exception:
        return None


# ---------------------------------------------------------
# API PREMIUM — Mapbox (PREPARATA MA DISATTIVATA)
# ---------------------------------------------------------
MAPBOX_TOKEN = None  # <-- pronto per quando me la dai

def _fetch_dem_mapbox(bbox):
    """Non attivo finché MAPBOX_TOKEN non viene fornito."""
    return None


# ---------------------------------------------------------
# PUBLIC: Fetch DEM ibrido
# ---------------------------------------------------------
def get_dem_for_polyline(
    polyline: List[Tuple[float, float]],
    padding_m: float = 80.0,
) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float, float, float]]]:

    bbox = _bbox_from_polyline(polyline, padding_m)
    if not bbox:
        return None, None

    # 1 → Mapbox (DISATTIVATO)
    if MAPBOX_TOKEN:
        data = _fetch_dem_mapbox(bbox)
        if data is not None:
            return data, bbox

    # 2 → ESRI
    data = _fetch_dem_esri(bbox)
    if data is not None:
        return data, bbox

    # 3 → SRTM fallback
    data = _fetch_dem_srtm(bbox)
    if data is not None:
        return data, bbox

    return None, bbox
