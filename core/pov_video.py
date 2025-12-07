# core/pov_video.py
# Generatore POV 3D (~12 s) da traccia pista + Mapbox Static API
#
# - Usa stile "mapbox/satellite-v9"
# - Camera bassa (zoom 16.3, pitch 72°) orientata lungo la pista
# - Limite sui punti del path per evitare errori 422
# - Limite sui frame per non saturare le chiamate a Mapbox
# - Output: GIF animata 1280x720 in ./videos/<slug>_pov_12s.gif

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

DURATION_S = 12.0       # durata target del POV
FPS = 14                # compromesso: abbastanza fluido, meno richieste

MIN_FRAMES = 40         # per non avere video troppo corti/scattosi
MAX_FRAMES = 140        # cap duro: evita troppe chiamate Mapbox

STYLE_ID = "mapbox/satellite-v9"  # satellite 3D standard Mapbox
LINE_COLOR = "ff4422"             # arancione/rosso pista
LINE_WIDTH = 4

MAX_PATH_POINTS = 60    # max vertici nella path-... → evita 422

# filtro neve disattivato (hook futuro)
ENABLE_SNOW_FILTER = False

UA = {"User-Agent": "telemark-wax-pro/POV-1.0"}


# -----------------------------------------------------
# Utilità base
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
            "MAPBOX_API_KEY non configurata in st.secrets o nelle variabili d'ambiente."
        )
    return token


def _as_points(
    track: Union[Dict[str, Any], Sequence[Dict[str, Any]]]
) -> List[Dict[str, float]]:
    """
    Normalizza l'input in lista di dict con chiavi 'lat'/'lon'.
    Supporta:
      - GeoJSON Feature LineString
      - lista di dict {"lat": ..., "lon": ...}
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

    # Lista di punti
    pts: List[Dict[str, float]] = []
    for p in track:  # type: ignore[assignment]
        lat = float(p.get("lat"))  # type: ignore[arg-type]
        lon = float(p.get("lon"))  # type: ignore[arg-type]
        pts.append({"lat": lat, "lon": lon})
    return pts


def _resample(points: List[Dict[str, float]], max_points: int) -> List[Dict[str, float]]:
    """
    Limita il numero di punti del path per non esplodere la URL
    (evita errori 422 da Mapbox).
    """
    n = len(points)
    if n <= max_points:
        return points

    step = max(1, n // max_points)
    out: List[Dict[str, float]] = []
    for i in range(0, n, step):
        out.append(points[i])
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def _bearing(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Azimut (0–360°) da punto a → b (gradi Mapbox: 0 = Nord, 90 = Est)."""
    lat1 = math.radians(a["lat"])
    lat2 = math.radians(b["lat"])
    dlon = math.radians(b["lon"] - a["lon"])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def _build_path_param(points: List[Dict[str, float]]) -> str:
    """
    Costruisce il parametro path-... per la Static API.
    Niente opacity esplicita (lasciamo default 1.0) per accorciare la URL.
    """
    pts = _resample(points, max_points=MAX_PATH_POINTS)
    coord_str = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in pts)
    return f"path-{LINE_WIDTH}+{LINE_COLOR}({coord_str})"


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

    zoom ≈ 16.3 + pitch 72° → camera bassa, vista tipo POV sciata.
    """
    url = (
        f"https://api.mapbox.com/styles/v1/{STYLE_ID}/static/"
        f"{path_param}/"
        f"{center['lon']:.5f},{center['lat']:.5f},{zoom:.2f},{bearing:.1f},{pitch:.1f}/"
        f"{WIDTH}x{HEIGHT}"
        f"?access_token={token}"
    )
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    return img


def _apply_snow_filter(img: Image.Image) -> Image.Image:
    """
    Hook per un eventuale filtro neve.
    Per ora è disattivato per non degradare troppo le immagini.
    """
    if not ENABLE_SNOW_FILTER:
        return img

    arr = np.asarray(img).astype("float32") / 255.0

    # leggero boost contrasto + tono appena più freddo
    arr = (arr - 0.5) * 1.05 + 0.5
    arr[..., 0] *= 0.98  # meno rosso
    arr[..., 2] *= 1.03  # un filo più blu
    arr = np.clip(arr, 0.0, 1.0)

    arr = (arr * 255.0).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


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

    track:
      - GeoJSON Feature LineString
      - oppure lista di punti {lat, lon, ...}

    Ritorna:
      percorso file GIF in ./videos/<slug>_pov_12s.gif
    """
    token = _get_mapbox_token()

    points = _as_points(track)
    if len(points) < 2:
        raise ValueError("Traccia pista troppo corta per generare un POV.")

    # Parametro path per mostrare tutta la pista in rosso
    path_param = _build_path_param(points)

    # Numero frame: clamp fra MIN_FRAMES e MAX_FRAMES
    n_frames = int(duration_s * fps)
    n_frames = max(MIN_FRAMES, min(n_frames, MAX_FRAMES))

    # Indici "float" lungo i segmenti (0 → n-2)
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

    # Scarico i frame da Mapbox
    frames: List[np.ndarray] = []

    for c, brng in zip(centers, bearings):
        img = _fetch_frame(token, c, brng, path_param)
        img = _apply_snow_filter(img)
        frames.append(np.asarray(img))

    # Salvataggio GIF
    out_dir = Path("videos")
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_" else "_" for ch in str(pista_name).lower()
    ) or "pista"
    out_path = out_dir / f"{safe_name}_pov_{int(duration_s)}s.gif"

    imageio.mimsave(str(out_path), frames, fps=fps)

    return str(out_path)
