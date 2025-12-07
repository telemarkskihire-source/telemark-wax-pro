# core/pov_video.py
# Generatore POV 3D (12 s) da traccia pista + Mapbox Static API
#
# - Usa stile satellitare Mapbox
# - Muove la "camera" lungo la pista con bearing dinamico
# - Salva una GIF 12 s in ./videos/<pista>_pov_12s.gif

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Union
import io
import math
import os
from pathlib import Path
import urllib.parse

import numpy as np
import requests
from PIL import Image
import imageio
import streamlit as st

# -----------------------------------------------------
# Config generale POV
# -----------------------------------------------------

WIDTH = 1280
HEIGHT = 720
DURATION_S = 12.0
FPS = 20  # più frame = movimento più fluido

STYLE_ID = "mapbox/satellite-v9"  # satellite standard Mapbox
LINE_COLOR = "ff4422"             # arancione/rosso per la pista
LINE_WIDTH = 4
LINE_OPACITY = 0.9                # 0–1

# -----------------------------------------------------
# Utilità
# -----------------------------------------------------


def _get_mapbox_token() -> str:
    """Legge la MAPBOX_API_KEY da st.secrets o ENV."""
    try:
        token = str(st.secrets.get("MAPBOX_API_KEY", "")).strip()
        if token:
            return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    if not token:
        raise RuntimeError(
            "MAPBOX_API_KEY non configurata in secrets o variabili d'ambiente."
        )
    return token


def _as_points(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]
) -> List[Dict[str, float]]:
    """
    Normalizza l'input in lista di dict con lat/lon:
    - GeoJSON Feature LineString
    - oppure lista di {lat, lon, ...}
    """
    # GeoJSON Feature
    if isinstance(track, dict) and track.get("type") == "Feature":
        geom = track.get("geometry") or {}
        if geom.get("type") != "LineString":
            raise ValueError("GeoJSON non è una LineString.")
        coords = geom.get("coordinates") or []
        pts: List[Dict[str, float]] = []
        for lon, lat in coords:
            pts.append({"lat": float(lat), "lon": float(lon)})
        return pts

    # Lista generica di punti
    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[assignment]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


def _resample(points: List[Dict[str, float]], max_points: int) -> List[Dict[str, float]]:
    """
    Riduce il numero di punti mantenendo la forma generale della pista.
    Usato SOLO per il path disegnato da Mapbox (non per l'animazione).
    """
    n = len(points)
    if n <= max_points:
        return points

    idx = np.linspace(0, n - 1, max_points).astype(int)
    return [points[i] for i in idx]


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Azimut (0–360°) da a → b."""
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _build_path_param(points: List[Dict[str, float]]) -> str:
    """
    Costruisce il parametro path-… per la Static API e lo URL-encoda.
    Usiamo fino a ~40 punti per disegnare la pista.
    """
    pts = _resample(points, max_points=40)

    coord_str = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)
    raw = f"path-{LINE_WIDTH}+{LINE_COLOR}-{LINE_OPACITY}({coord_str})"

    # 🔥 encoding obbligatorio, altrimenti Mapbox risponde 422
    encoded = urllib.parse.quote(raw, safe="")
    return encoded


def _fetch_frame(
    token: str,
    center: Dict[str, float],
    bearing: float,
    path_param: str,
    zoom: float = 16.3,
    pitch: float = 72.0,
) -> Image.Image:
    """
    Scarica un singolo frame statico da Mapbox.

    zoom 16.3 + pitch 72° → camera bassa, tipo POV sciata (non troppo dall'alto).
    """
    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{path_param}/"
        f"{center['lon']:.5f},{center['lat']:.5f},{zoom:.2f},{bearing:.1f},{pitch:.1f}/"
        f"{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )
    r = requests.get(url, timeout=25)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    return img


# -----------------------------------------------------
# Funzione principale usata da streamlit_app
# -----------------------------------------------------


def generate_pov_video(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]],
    pista_name: str,
    duration_s: float = DURATION_S,
    fps: int = FPS,
) -> str:
    """
    Genera una GIF POV 3D di ~duration_s secondi.

    track: GeoJSON Feature LineString oppure lista di punti {lat, lon, ...}
    Ritorna: percorso del file GIF in ./videos/<nome>_pov_12s.gif
    """
    token = _get_mapbox_token()

    points = _as_points(track)
    if len(points) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    # Path disegnato sulla mappa (usiamo fino a ~40 punti, URL-encoded)
    path_param = _build_path_param(points)

    # Timeline: ci muoviamo lungo *tutta* la pista
    n_frames = int(duration_s * fps)
    if n_frames < 2:
        n_frames = 2

    # campioniamo tra il primo e il penultimo punto (segmenti a→b)
    idx_float = np.linspace(0, len(points) - 2, n_frames)

    centers: List[Dict[str, float]] = []
    bearings: List[float] = []

    for t in idx_float:
        i = int(math.floor(t))
        frac = float(t - i)

        a = points[i]
        b = points[i + 1]

        lat = a["lat"] + (b["lat"] - a["lat"]) * frac
        lon = a["lon"] + (b["lon"] - a["lon"]) * frac

        centers.append({"lat": lat, "lon": lon})
        bearings.append(_bearing(a, b))

    frames: List[np.ndarray] = []

    for c, brng in zip(centers, bearings):
        img = _fetch_frame(token, c, brng, path_param)
        frames.append(np.asarray(img))

    # salvataggio GIF
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    )
    out_path = out_dir / f"{safe_name}_pov_12s.gif"

    imageio.mimsave(str(out_path), frames, fps=fps)

    return str(out_path)
