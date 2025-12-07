# core/pov_video.py
# Generatore POV 3D (12 s) da traccia pista con Mapbox Static Images
#
# - La camera segue la pista in modo fluido
# - Nessun overlay "path-..." → niente errori 422
# - Pitch alto (quasi visuale sciatore)
# - Export MP4, con fallback automatico a GIF

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Union
import io
import math
import os
from pathlib import Path

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

# Parametri "camera"
ZOOM = 16.3        # abbastanza vicino
PITCH = 72.0       # visuale molto inclinata (quasi prima persona)


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
    """Normalizza l'input in lista di dict con lat/lon."""
    if isinstance(track, dict) and track.get("type") == "Feature":
        # GeoJSON LineString
        geom = track.get("geometry") or {}
        if geom.get("type") != "LineString":
            raise ValueError("GeoJSON non è una LineString.")
        coords = geom.get("coordinates") or []
        pts: List[Dict[str, float]] = []
        for lon, lat in coords:
            pts.append({"lat": float(lat), "lon": float(lon)})
        return pts

    # Lista di punti {lat, lon, ...}
    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[assignment]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


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


def _fetch_frame(
    token: str,
    center: Dict[str, float],
    bearing: float,
) -> Image.Image:
    """
    Scarica un singolo frame statico da Mapbox.

    Usiamo solo il centro della camera: niente overlay → URL corto e robusto.
    """
    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{center['lon']:.5f},{center['lat']:.5f},"
        f"{ZOOM:.2f},{bearing:.1f},{PITCH:.1f}/"
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
    Genera un POV 3D di ~duration_s secondi che segue la pista.

    track: GeoJSON Feature LineString oppure lista di punti {lat, lon, ...}
    Ritorna: percorso del file video in ./videos/<nome>_pov_12s.mp4 (o .gif fallback).
    """
    token = _get_mapbox_token()

    points = _as_points(track)
    if len(points) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    n_frames = int(duration_s * fps)
    if n_frames < 2:
        n_frames = 2

    # Campioniamo lungo la linea
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
        img = _fetch_frame(token, c, brng)
        frames.append(np.asarray(img))

    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    )

    # -------------------------------------------------
    # Tentiamo prima MP4; se fallisce → GIF
    # -------------------------------------------------
    mp4_path = out_dir / f"{safe_name}_pov_12s.mp4"
    gif_path = out_dir / f"{safe_name}_pov_12s.gif"

    try:
        # imageio utilizza ffmpeg; se non c'è, genererà un errore
        writer = imageio.get_writer(
            str(mp4_path),
            fps=fps,
            codec="libx264",
            format="FFMPEG",
            mode="I",
        )
        for frame in frames:
            writer.append_data(frame)
        writer.close()
        return str(mp4_path)
    except Exception:
        # fallback sicuro
        imageio.mimsave(str(gif_path), frames, fps=fps)
        return str(gif_path)
