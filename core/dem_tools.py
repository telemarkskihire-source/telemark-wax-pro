# core/dem_tools.py
# DEM ibrido per Telemark · Pro Wax & Tune
#
# - get_dem_for_polyline(polyline): ritorna (array DEM, bbox)
# - render_dem(T, ctx): wrapper visivo (compatibilità con app)
#
# Fonti:
#   1) ESRI WorldElevation (stabile)
#   2) SRTM fallback
#   3) Mapbox (prep, ma disattivato finché non fornisci token)

from __future__ import annotations

from typing import List, Tuple, Optional, Any

import math
import numpy as np
import requests
import rasterio
from rasterio.io import MemoryFile
import streamlit as st
import pandas as pd
import altair as alt

UA = {"User-Agent": "telemark-wax-pro/3.0"}

# ---------------------------------------------------------
# Utilità coordinate
# ---------------------------------------------------------
def _valid_coord(lat: float, lon: float) -> bool:
    """Coordinate realistiche per Italia / Alpi (per evitare piste nel Pacifico)."""
    return 35.0 < lat < 47.7 and 5.0 < lon < 13.7


def _bbox_from_polyline(
    poly: List[Tuple[float, float]],
    padding_m: float = 80.0,
) -> Optional[Tuple[float, float, float, float]]:
    """Bounding box con un po' di margine attorno alla pista."""
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
# DEM SOURCE 1 — ESRI WorldElevation
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
                data = src.read(1)
                return data
    except Exception:
        return None


# ---------------------------------------------------------
# DEM SOURCE 2 — SRTM fallback
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_dem_srtm(
    bbox: Tuple[float, float, float, float]
) -> Optional[np.ndarray]:
    """
    Fallback molto semplice: prende la tile SRTM corrispondente al canto SW.
    Non è perfetto, ma meglio di niente.
    """
    min_lat, min_lon, max_lat, max_lon = bbox

    tile_lat = int(math.floor(min_lat))
    tile_lon = int(math.floor(min_lon))

    url = (
        "https://s3.amazonaws.com/elevation-tiles-prod/skadi/"
        f"{tile_lat:+03d}{tile_lon:+04d}.tif"
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
# DEM SOURCE 3 — Mapbox (preparato ma disattivato)
# ---------------------------------------------------------
MAPBOX_TOKEN: Optional[str] = None  # metti la tua pk.xxx qui quando vuoi

def _fetch_dem_mapbox(
    bbox: Tuple[float, float, float, float]
) -> Optional[np.ndarray]:
    """Placeholder: attivo solo se imposti MAPBOX_TOKEN."""
    if not MAPBOX_TOKEN:
        return None
    # Qui potremo aggiungere in futuro integrazione con terrain-rgb
    return None


# ---------------------------------------------------------
# PUBLIC: DEM ibrido
# ---------------------------------------------------------
def get_dem_for_polyline(
    polyline: List[Tuple[float, float]],
    padding_m: float = 80.0,
) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float, float, float]]]:
    """
    Ritorna:
      - dem_data: np.ndarray o None
      - bbox: (min_lat, min_lon, max_lat, max_lon) o None
    """
    bbox = _bbox_from_polyline(polyline, padding_m)
    if not bbox:
        return None, None

    # 1) Mapbox (se un giorno attiviamo)
    data = _fetch_dem_mapbox(bbox)
    if data is not None:
        return data, bbox

    # 2) ESRI
    data = _fetch_dem_esri(bbox)
    if data is not None:
        return data, bbox

    # 3) SRTM fallback
    data = _fetch_dem_srtm(bbox)
    if data is not None:
        return data, bbox

    return None, bbox


# ---------------------------------------------------------
# Wrapper compatibilità: render_dem(T, ctx)
# ---------------------------------------------------------
def render_dem(T: dict, ctx: dict) -> dict:
    """
    Vista DEM generica per la pagina 'Località & Mappa'.
    Usa, se disponibile:
      - ctx["pov_piste_points"]
    Altrimenti, se non c'è pista, non fa danni.
    """
    piste = ctx.get("pov_piste_points")

    if not piste:
        st.info("DEM non disponibile: nessuna pista selezionata (POV non ancora attivo).")
        return ctx

    with st.spinner("Carico modello altimetrico (DEM)…"):
        dem, bbox = get_dem_for_polyline(piste)

    if dem is None:
        st.info("DEM non disponibile al momento (ESRI/SRTM).")
        return ctx

    vals = dem.flatten()
    vals = vals[np.isfinite(vals)]

    if vals.size == 0:
        st.info("DEM senza dati validi.")
        return ctx

    df = pd.DataFrame({"quota_m": vals})
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("quota_m:Q", bin=alt.Bin(maxbins=40), title="Quota (m)"),
            y=alt.Y("count():Q", title="Numero celle"),
        )
        .properties(height=160, title="Distribuzione quote DEM lungo la pista")
    )
    st.markdown("### 🗺️ DEM pista")
    st.altair_chart(chart, use_container_width=True)

    st.caption(
        f"Altitudine media: {vals.mean():.0f} m · "
        f"min: {vals.min():.0f} m · max: {vals.max():.0f} m"
    )

    return ctx
