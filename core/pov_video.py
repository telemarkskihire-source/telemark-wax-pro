# core/pov_video.py
# POV 3D in stile "sciatore" da traccia pista + Mapbox Static API
#
# - Usa Mapbox Static Images (satellite-v9)
# - Usa Mapbox Terrain-RGB per stimare altitudine e pendenza
# - Camera bassa, puntata in avanti lungo la pista
# - Salva un MP4 12 s in ./videos/<nome>_pov_12s.mp4

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple, Union
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
FPS = 24  # movimento più fluido

STYLE_ID = "mapbox/satellite-v9"  # satellite 3D standard Mapbox
LINE_COLOR = "ff4422"             # arancione/rosso per la pista
LINE_WIDTH = 4

# zoom/pitch medi: poi li moduliamo leggermente
BASE_ZOOM = 16.0        # abbastanza vicino
MIN_PITCH = 47.0        # gradi (0 = vista dall'alto, 60 = quasi orizzonte)
MAX_PITCH = 60.0

UA = {"User-Agent": "telemark-wax-pro/4.0"}

# Cache in memoria per le tile Terrain-RGB
_TERRAIN_CACHE: Dict[Tuple[int, int, int], np.ndarray] = {}

# -----------------------------------------------------
# Utilità generali
# -----------------------------------------------------

def _get_mapbox_token() -> str:
    """Legge MAPBOX_API_KEY da st.secrets o da variabile d'ambiente."""
    try:
        token = str(st.secrets.get("MAPBOX_API_KEY", "")).strip()
        if token:
            return token
    except Exception:
        pass

    token = os.environ.get("MAPBOX_API_KEY", "").strip()
    if not token:
        raise RuntimeError(
            "MAPBOX_API_KEY non configurata (né in secrets né in variabili d'ambiente)."
        )
    return token


def _as_points(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]
) -> List[Dict[str, float]]:
    """
    Normalizza l'input in una lista di dict {lat, lon}.
    Accetta:
      - GeoJSON Feature con LineString
      - Lista di dict con chiavi 'lat' e 'lon'
    """
    if isinstance(track, dict) and track.get("type") == "Feature":
        geom = track.get("geometry") or {}
        if geom.get("type") != "LineString":
            raise ValueError("GeoJSON non è una LineString.")
        coords = geom.get("coordinates") or []
        pts: List[Dict[str, float]] = []
        for lon, lat in coords:
            pts.append({"lat": float(lat), "lon": float(lon)})
        return pts

    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[assignment]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


def _haversine_m(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Distanza in metri fra due punti lat/lon."""
    R = 6371000.0
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlat = lat2 - lat1
    dlon = math.radians(b["lon"] - a["lon"])
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(h), math.sqrt(1.0 - h))
    return R * c


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Azimut (0–360°) da a → b (0 = Nord, 90 = Est)."""
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _resample_for_path(points: List[Dict[str, float]], max_points: int = 100) -> List[Dict[str, float]]:
    """
    Semplifica la traccia per il parametro 'path' di Mapbox,
    tenendo l'ordine e i punti estremi.
    """
    n = len(points)
    if n <= max_points:
        return points

    step = max(1, n // max_points)
    out: List[Dict[str, float]] = points[::step]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _build_path_param(points: List[Dict[str, float]]) -> str:
    """
    Costruisce il parametro path corretto per la Static API.
    ATTENZIONE: niente opacity nel path, altrimenti 422.
    """
    pts = _resample_for_path(points, max_points=80)
    coord_str = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)
    return f"path-{LINE_WIDTH}+{LINE_COLOR}({coord_str})"

# -----------------------------------------------------
# Terrain-RGB (DEM)
# -----------------------------------------------------

def _latlon_to_tile(
    lat: float, lon: float, z: int
) -> Tuple[int, int, float, float]:
    """
    Converte lat/lon in tile (x, y) a zoom z + posizione relativa dentro la tile.
    Ritorna: x, y, fx, fy (fx, fy ∈ [0, 1])
    """
    lat_rad = math.radians(lat)
    n = 2.0 ** z
    xtile_f = (lon + 180.0) / 360.0 * n
    ytile_f = (
        (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )

    xtile = int(xtile_f)
    ytile = int(ytile_f)
    fx = xtile_f - xtile
    fy = ytile_f - ytile
    return xtile, ytile, fx, fy


def _fetch_terrain_tile(z: int, x: int, y: int, token: str) -> np.ndarray:
    """
    Scarica una tile Terrain-RGB e la converte in m di altitudine (array 256×256).
    Usa cache in memoria per non rifare la stessa richiesta più volte.
    """
    key = (z, x, y)
    if key in _TERRAIN_CACHE:
        return _TERRAIN_CACHE[key]

    url = (
        f"https://api.mapbox.com/v4/mapbox.terrain-rgb/"
        f"{z}/{x}/{y}.pngraw?access_token={token}"
    )
    r = requests.get(url, timeout=15, headers=UA)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    arr = np.asarray(img).astype("float32")

    # formula Mapbox: height(m) = -10000 + (R*256^2 + G*256 + B) * 0.1
    R = arr[..., 0]
    G = arr[..., 1]
    B = arr[..., 2]
    height_m = -10000.0 + (R * 256.0 * 256.0 + G * 256.0 + B) * 0.1

    _TERRAIN_CACHE[key] = height_m
    return height_m


def _terrain_height(lat: float, lon: float, token: str, z: int = 13) -> float:
    """
    Ritorna altitudine in metri per (lat, lon) usando Terrain-RGB.
    Usa bilinear interpolation dentro la tile.
    Se qualcosa va storto, restituisce 0.0 (poi gestito a valle).
    """
    try:
        x, y, fx, fy = _latlon_to_tile(lat, lon, z)
        tile = _fetch_terrain_tile(z, x, y, token)

        # posizioni in pixel dentro la tile
        px = fx * 255.0
        py = fy * 255.0

        x0 = int(math.floor(px))
        x1 = min(255, x0 + 1)
        y0 = int(math.floor(py))
        y1 = min(255, y0 + 1)

        dx = px - x0
        dy = py - y0

        # bilinear
        h00 = tile[y0, x0]
        h10 = tile[y0, x1]
        h01 = tile[y1, x0]
        h11 = tile[y1, x1]

        h0 = h00 * (1.0 - dx) + h10 * dx
        h1 = h01 * (1.0 - dx) + h11 * dx
        h = h0 * (1.0 - dy) + h1 * dy

        return float(h)
    except Exception:
        return 0.0


def _compute_altitude_profile(
    points: List[Dict[str, float]],
    token: str,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    Costruisce:
      - alt_m[i]   = quota in metri del punto i
      - slope_deg[i] ≈ pendenza del segmento i→i+1 (ultimo replicato)
      - total_len_m = lunghezza totale pista
    """
    n = len(points)
    alt = np.zeros(n, dtype="float32")
    for i, p in enumerate(points):
        alt[i] = _terrain_height(p["lat"], p["lon"], token, z=13)

    # distanze e pendenze lungo la pista
    dists = np.zeros(n - 1, dtype="float32")
    slopes = np.zeros(n - 1, dtype="float32")

    for i in range(n - 1):
        a = points[i]
        b = points[i + 1]
        d = _haversine_m(a, b)
        dists[i] = max(d, 0.1)  # evitiamo 0

        dz = alt[i + 1] - alt[i]
        slope_rad = math.atan2(abs(dz), dists[i])
        slopes[i] = math.degrees(slope_rad)

    if n >= 2:
        slopes_full = np.concatenate([slopes, slopes[-1:]])
    else:
        slopes_full = np.zeros_like(alt)

    total_len = float(np.sum(dists))
    return alt, slopes_full, total_len

# -----------------------------------------------------
# Static frame da Mapbox
# -----------------------------------------------------

def _fetch_frame(
    token: str,
    center: Dict[str, float],
    bearing: float,
    path_param: str,
    pitch_deg: float,
    zoom: float,
) -> Image.Image:
    """
    Scarica un singolo frame statico da Mapbox.
    pitch 45–60°: camera bassa, quasi in prima persona.
    """
    pitch_clamped = max(MIN_PITCH, min(MAX_PITCH, pitch_deg))
    zoom_clamped = max(10.0, min(18.0, zoom))

    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{path_param}/"
        f"{center['lon']:.5f},{center['lat']:.5f},"
        f"{zoom_clamped:.2f},{bearing:.1f},{pitch_clamped:.1f}/"
        f"{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )

    r = requests.get(url, timeout=30, headers=UA)
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
    Genera un POV 3D in formato MP4 (~duration_s secondi).

    track:
      - GeoJSON Feature LineString
      - oppure lista di punti {lat, lon, ...}

    Ritorna:
      percorso del file MP4 in ./videos/<nome>_pov_12s.mp4
    """
    token = _get_mapbox_token()

    points_raw = _as_points(track)
    if len(points_raw) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    # Semplifichiamo leggermente la traccia per il percorso camera
    # (manteniamo comunque tutti i punti per il DEM)
    points = points_raw

    # Parametro path (disegno pista a terra)
    path_param = _build_path_param(points)

    # Profilo altimetrico + pendenza
    alt_m, slope_deg, total_len_m = _compute_altitude_profile(points, token)
    n_points = len(points)

    # Timeline: frame distribuiti uniformemente lungo la lunghezza totale
    n_frames = int(duration_s * fps)
    n_frames = max(24, n_frames)  # almeno 1 s

    if total_len_m <= 0.0 or n_points < 2:
        # fallback: nessuna informazione dem, camera costante
        total_len_m = float(n_points - 1) or 1.0

    frame_pos = np.linspace(0.0, total_len_m - 1e-6, n_frames)

    # distanza cumulativa per ogni punto della traccia
    cum_dist = np.zeros(n_points, dtype="float32")
    for i in range(1, n_points):
        cum_dist[i] = cum_dist[i - 1] + _haversine_m(points[i - 1], points[i])

    frames: List[np.ndarray] = []

    for s in frame_pos:
        # Trova il segmento corrispondente alla distanza s
        idx = int(np.searchsorted(cum_dist, s, side="right") - 1)
        idx = max(0, min(idx, n_points - 2))

        # frazione lungo il segmento
        seg_start = cum_dist[idx]
        seg_len = max(cum_dist[idx + 1] - seg_start, 0.1)
        frac = float((s - seg_start) / seg_len)
        frac = max(0.0, min(1.0, frac))

        a = points[idx]
        b = points[idx + 1]

        # centro camera interpolato lungo la pista
        lat = a["lat"] + (b["lat"] - a["lat"]) * frac
        lon = a["lon"] + (b["lon"] - a["lon"]) * frac
        center = {"lat": lat, "lon": lon}

        # direzione di marcia: bearing del segmento
        brng = _bearing(a, b)

        # pendenza locale
        local_slope = float(slope_deg[idx])
        # pitch: più ripido = più "in orizzonte"
        pitch = MIN_PITCH + min(1.0, local_slope / 30.0) * (MAX_PITCH - MIN_PITCH)

        # zoom: leggero zoom in sulle parti ripide
        zoom = BASE_ZOOM + min(1.0, local_slope / 35.0) * 0.6

        img = _fetch_frame(token, center, brng, path_param, pitch, zoom)
        frames.append(np.asarray(img))

    # ----------------- Salvataggio MP4 -----------------
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    )
    out_path = out_dir / f"{safe_name}_pov_12s.mp4"

    # H.264, qualità medio-alta
    with imageio.get_writer(
        str(out_path),
        fps=fps,
        codec="libx264",
        quality=8,
        ffmpeg_log_level="error",
    ) as writer:
        for frame in frames:
            writer.append_data(frame)

    return str(out_path)
