# core/pov_video.py
# Generatore POV 3D da traccia pista + Mapbox (Satellite + Terrain-RGB)
#
# - Input: GeoJSON LineString oppure lista di punti {lat, lon, [elev]}
# - Output: MP4 ~12 s, 30 FPS, camera bassa tipo sciatore
# - Usa:
#     · Static Images API per le immagini prospettiche
#     · Tiles Terrain-RGB per stimare la pendenza (pitch dinamico)
#
# File di output:
#   ./videos/<slug_pista>_pov_12s.mp4

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Union, Tuple
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
# Config POV
# -----------------------------------------------------

# limiti Static API: max 1280 px per lato
WIDTH = 1280
HEIGHT = 720

DURATION_S = 12.0       # durata target
FPS = 30                # fps output
MAX_UNIQUE_FRAMES = 80  # massimo numero di frame UNICI scaricati da Mapbox

STYLE_ID = "mapbox/satellite-v9"
LINE_COLOR = "ff4422"
LINE_WIDTH = 4
LINE_OPACITY = 0.9

# Terrain-RGB
TERRAIN_TILESET = "mapbox.terrain-rgb"
TERRAIN_ZOOM = 13
SLOPE_WINDOW = 2  # punti prima/dopo per pendenza locale

# camera
PITCH_BASE_DEG = 60.0
PITCH_SLOPE_GAIN = 0.4
ZOOM_LEVEL = 16.3

# neve/filtro (disattivato)
ENABLE_SNOW_FILTER = False


# -----------------------------------------------------
# Token Mapbox
# -----------------------------------------------------
def _get_mapbox_token() -> str:
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


# -----------------------------------------------------
# Geo helpers & Terrain-RGB
# -----------------------------------------------------
def _haversine_m(a: Dict[str, float], b: Dict[str, float]) -> float:
    R = 6371000.0
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlat = math.radians(b["lat"] - a["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    h = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(h), math.sqrt(1.0 - h))
    return R * c


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
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


def _latlon_to_tile(lat: float, lon: float, z: int) -> Tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )
    return x, y


def _latlon_to_pixel(
    lat: float, lon: float, z: int, x_tile: int, y_tile: int
) -> Tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (
        1.0
        - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi
    ) / 2.0 * n

    rel_x = (x - x_tile) * 256.0
    rel_y = (y - y_tile) * 256.0
    return int(rel_x), int(rel_y)


def _decode_terrain_rgb(r: int, g: int, b: int) -> float:
    return (r * 256.0 * 256.0 + g * 256.0 + b) / 10.0 - 10000.0


def _fetch_terrain_tile(
    token: str,
    z: int,
    x: int,
    y: int,
    cache: Dict[Tuple[int, int, int], np.ndarray],
) -> np.ndarray:
    key = (z, x, y)
    if key in cache:
        return cache[key]

    url = (
        f"https://api.mapbox.com/v4/{TERRAIN_TILESET}/{z}/{x}/{y}.pngraw"
        f"?access_token={token}"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    arr = np.asarray(img, dtype=np.uint8)
    cache[key] = arr
    return arr


def _get_elevation_m(
    token: str,
    lat: float,
    lon: float,
    cache: Dict[Tuple[int, int, int], np.ndarray],
) -> float:
    z = TERRAIN_ZOOM
    x_tile, y_tile = _latlon_to_tile(lat, lon, z)
    tile = _fetch_terrain_tile(token, z, x_tile, y_tile, cache)
    px, py = _latlon_to_pixel(lat, lon, z, x_tile, y_tile)
    px = max(0, min(255, px))
    py = max(0, min(255, py))
    r, g, b = tile[py, px]
    return float(_decode_terrain_rgb(int(r), int(g), int(b)))


# -----------------------------------------------------
# Normalizzazione traccia & resampling
# -----------------------------------------------------
def _as_points(track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]) -> List[Dict[str, float]]:
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


def _resample_by_distance(
    points: List[Dict[str, float]],
    step_m: float = 20.0,
) -> List[Dict[str, float]]:
    if len(points) < 2:
        return points

    out: List[Dict[str, float]] = [points[0]]
    acc = 0.0

    for i in range(1, len(points)):
        a = out[-1]
        b = points[i]
        d = _haversine_m(a, b)
        if d + acc >= step_m and d > 0:
            need = step_m - acc
            frac = max(0.0, min(1.0, need / d))
            lat = a["lat"] + (b["lat"] - a["lat"]) * frac
            lon = a["lon"] + (b["lon"] - a["lon"]) * frac
            out.append({"lat": lat, "lon": lon})
            acc = 0.0
        else:
            acc += d

    if out[-1] is not points[-1]:
        out.append(points[-1])

    return out


# -----------------------------------------------------
# Path param (linea pista)
# -----------------------------------------------------
def _build_path_param(points: List[Dict[str, float]]) -> str:
    max_points = 80
    n = len(points)
    if n > max_points:
        step = max(1, n // max_points)
        pts = points[::step]
        if pts[-1] is not points[-1]:
            pts.append(points[-1])
    else:
        pts = points

    coord_str = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)
    return f"path-{LINE_WIDTH}+{LINE_COLOR}-{LINE_OPACITY}({coord_str})"


# -----------------------------------------------------
# Frame singolo da Mapbox
# -----------------------------------------------------
def _fetch_frame(
    token: str,
    center: Dict[str, float],
    bearing: float,
    pitch_deg: float,
    path_param: str,
) -> Image.Image:
    pitch_clamped = max(0.0, min(60.0, pitch_deg))

    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{path_param}/"
        f"{center['lon']:.5f},{center['lat']:.5f},{ZOOM_LEVEL:.2f},"
        f"{bearing:.1f},{pitch_clamped:.1f}/"
        f"{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    return img


def _apply_snow_filter(img: Image.Image) -> Image.Image:
    if not ENABLE_SNOW_FILTER:
        return img

    arr = np.asarray(img).astype("float32") / 255.0
    arr = (arr - 0.5) * 1.06 + 0.5
    arr[..., 0] *= 0.97
    arr[..., 2] *= 1.02
    arr = np.clip(arr, 0.0, 1.0)
    arr = (arr * 255.0).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


# -----------------------------------------------------
# Profilo altimetrico & pendenze
# -----------------------------------------------------
def _build_elevation_profile(
    token: str,
    points: List[Dict[str, float]],
) -> Tuple[List[float], List[float]]:
    cache: Dict[Tuple[int, int, int], np.ndarray] = {}
    elev: List[float] = []

    for p in points:
        z = _get_elevation_m(token, p["lat"], p["lon"], cache)
        elev.append(z)

    slopes: List[float] = []
    n = len(points)

    for i in range(n):
        j0 = max(0, i - SLOPE_WINDOW)
        j1 = min(n - 1, i + SLOPE_WINDOW)
        a = points[j0]
        b = points[j1]
        dz = elev[j0] - elev[j1]
        dist = max(1.0, _haversine_m(a, b))
        angle = math.degrees(math.atan2(dz, dist))
        angle = max(0.0, min(70.0, angle))
        slopes.append(angle)

    return elev, slopes


# -----------------------------------------------------
# Funzione principale
# -----------------------------------------------------
def generate_pov_video(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]],
    pista_name: str,
    duration_s: float = DURATION_S,
    fps: int = FPS,
) -> str:
    """
    Genera POV 3D ~duration_s (MP4 1280x720, 30 FPS) in ./videos/<slug>_pov_12s.mp4
    """
    token = _get_mapbox_token()

    # 1) Normalizzazione & resampling pista
    points_raw = _as_points(track)
    if len(points_raw) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    points = _resample_by_distance(points_raw, step_m=20.0)
    if len(points) < 2:
        points = points_raw

    # 2) Profilo altimetrico + pendenze
    _, slopes_deg = _build_elevation_profile(token, points)

    # 3) Timeline logica dei frame
    target_frames = max(10, int(duration_s * fps))          # es. 12*30 = 360
    n_unique = min(MAX_UNIQUE_FRAMES, target_frames)        # es. 80
    idx_float = np.linspace(0.0, len(points) - 2.0, n_unique)

    centers: List[Dict[str, float]] = []
    bearings: List[float] = []
    pitches: List[float] = []

    for t in idx_float:
        i = int(math.floor(t))
        frac = float(t - i)

        a = points[i]
        b = points[i + 1]

        lat = a["lat"] + (b["lat"] - a["lat"]) * frac
        lon = a["lon"] + (b["lon"] - a["lon"]) * frac
        centers.append({"lat": lat, "lon": lon})

        brng = _bearing(a, b)
        bearings.append(brng)

        slope_a = slopes_deg[i]
        slope_b = slopes_deg[i + 1]
        slope_here = slope_a + (slope_b - slope_a) * frac
        pitch = PITCH_BASE_DEG + slope_here * PITCH_SLOPE_GAIN
        pitches.append(pitch)

    # 4) path per overlay
    path_param = _build_path_param(points)

    # 5) Scarichiamo SOLO n_unique frame da Mapbox
    unique_frames: List[np.ndarray] = []
    for center, brng, pitch in zip(centers, bearings, pitches):
        img = _fetch_frame(token, center, brng, pitch, path_param)
        img = _apply_snow_filter(img)
        unique_frames.append(np.asarray(img))

    # 6) Duplichiamo i frame per arrivare alla durata desiderata
    frames: List[np.ndarray] = []
    if n_unique >= target_frames:
        frames = unique_frames[:target_frames]
    else:
        base_rep = target_frames // n_unique
        extra = target_frames % n_unique
        for i, frame in enumerate(unique_frames):
            rep = base_rep + (1 if i < extra else 0)
            for _ in range(rep):
                frames.append(frame)

    # 7) Salvataggio video
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    )
    out_path = out_dir / f"{safe_name}_pov_12s.mp4"

    try:
        with imageio.get_writer(
            str(out_path),
            fps=fps,
            codec="libx264",
            quality=8,
        ) as writer:
            for frame in frames:
                writer.append_data(frame)
    except Exception:
        # fallback GIF se libx264 non disponibile
        gif_path = out_dir / f"{safe_name}_pov_12s.gif"
        imageio.mimsave(str(gif_path), frames, fps=fps)
        return str(gif_path)

    return str(out_path)
