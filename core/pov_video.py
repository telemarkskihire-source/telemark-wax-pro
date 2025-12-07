# core/pov_video.py
# Generatore POV 3D da traccia pista + Mapbox Static API
#
# - Usa satellite Mapbox con camera bassa (tipo sciatore)
# - Durata ~12 s, FPS 25
# - Limite duro: max 60 punti nel path → niente 422
# - Output MP4 (fallback automatico a GIF se qualcosa va storto)

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Union
import io
import math
import os
from pathlib import Path

import numpy as np
import requests
from PIL import Image
import imageio.v2 as imageio
import streamlit as st

# -----------------------------------------------------
# Config generale POV
# -----------------------------------------------------

WIDTH = 1280
HEIGHT = 720
DURATION_S = 12.0
FPS = 25  # movimento più fluido

STYLE_ID = "mapbox/satellite-v9"  # stile base
LINE_COLOR = "ff4422"             # arancione/rosso per la pista
LINE_WIDTH = 4
LINE_OPACITY = 0.9                # 0–1

MAX_PATH_POINTS = 60              # limite duro per il path static API


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
        raise RuntimeError("MAPBOX_API_KEY non configurata in secrets o variabili d'ambiente.")
    return token


def _as_points(track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]) -> List[Dict[str, float]]:
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

    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[arg-type]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


def _resample_even(points: List[Dict[str, float]], max_points: int) -> List[Dict[str, float]]:
    """
    Riduce la lista di punti a max_points sample distribuiti uniformemente.
    Garantisce: len(out) <= max_points e include primo/ultimo.
    """
    n = len(points)
    if n <= max_points:
        return points

    idxs = np.linspace(0, n - 1, max_points).astype(int)
    out = [points[i] for i in idxs]
    return out


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Azimut (0–360°) da a → b."""
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _smooth_bearings(bearings: List[float], window: int = 5) -> List[float]:
    """
    Piccolo smoothing sulle rotazioni per evitare scatti di camera.
    """
    if len(bearings) <= window:
        return bearings

    arr = np.array(bearings, dtype=float)
    pad = window // 2
    padded = np.pad(arr, (pad, pad), mode="edge")
    kernel = np.ones(window) / float(window)
    sm = np.convolve(padded, kernel, mode="valid")
    return sm.tolist()


def _build_path_param(points: List[Dict[str, float]]) -> str:
    """Costruisce il parametro path-... per la Static API, con limite duro a MAX_PATH_POINTS."""
    pts = _resample_even(points, max_points=MAX_PATH_POINTS)
    coord_str = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)
    # path-{width}+{color}-{opacity}(...)
    return f"path-{LINE_WIDTH}+{LINE_COLOR}-{LINE_OPACITY}({coord_str})"


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

    zoom 16.3 + pitch 72° → camera bassa, tipo POV sciatore.
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
    Genera un POV 3D in formato MP4 (fallback GIF) di circa duration_s secondi.

    track: GeoJSON Feature LineString oppure lista di punti {lat, lon, ...}
    Ritorna: percorso del file creato in ./videos/<nome>_pov_12s.(mp4|gif)
    """
    token = _get_mapbox_token()

    points = _as_points(track)
    if len(points) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    # path completo (per avere la pista disegnata nel frame)
    path_param = _build_path_param(points)

    # timeline frame: ci muoviamo lungo la pista
    n_frames = int(duration_s * fps)
    if n_frames < 2:
        n_frames = 2

    idx_float = np.linspace(0.0, len(points) - 2.0, n_frames)

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

    bearings = _smooth_bearings(bearings, window=7)

    frames: List[np.ndarray] = []
    for c, brng in zip(centers, bearings):
        img = _fetch_frame(token, c, brng, path_param)
        frames.append(np.asarray(img))

    # salvataggio file
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    )
    mp4_path = out_dir / f"{safe_name}_pov_12s.mp4"

    try:
        # MP4 H.264
        writer = imageio.get_writer(str(mp4_path), fps=fps, codec="libx264")
        for frame in frames:
            writer.append_data(frame)
        writer.close()
        return str(mp4_path)
    except Exception:
        # Fallback: GIF animata
        gif_path = out_dir / f"{safe_name}_pov_12s.gif"
        imageio.mimsave(str(gif_path), frames, fps=fps)
        return str(gif_path)
